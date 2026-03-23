/**
 * Pipeline Store
 *
 * Central state management for pipeline items using Zustand.
 * Composed from focused slice modules — state shape is identical to before.
 */

import { create } from 'zustand'
import type { PipelineItem, PipelineStatus, RepoHealthTarget } from '../api/types'
import { isPRReady, getSeverityFromLabels, hyphenatedToSlashed } from '../utils'
import { createVibeCheckSlice, type VibeCheckSliceState } from './vibeCheckStore'
import { createOSSSlice, type OSSSliceState } from './ossStore'
import { createUISlice, type UISliceState } from './uiStore'
import { createFilterSlice, type FilterSliceState } from './filterStore'

// Re-export types that consumers import from this module
export type { ViewType, LogEntry } from './uiStore'

// ============ Combined State ============

interface PipelineState extends VibeCheckSliceState, OSSSliceState, UISliceState, FilterSliceState {
  // Pipeline items (derived from stage data)
  pipelineItems: PipelineItem[]

  // Core action that rebuilds pipelineItems from all stage data
  refreshPipelineItems: () => void
}

// ============ Pipeline Item Registry ============

type ItemMapper = (state: PipelineState) => PipelineItem[]

const pipelineItemProviders = new Map<string, ItemMapper>()

export function registerPipelineItemProvider(type: string, mapper: ItemMapper) {
  pipelineItemProviders.set(type, mapper)
}

// ============ Item Mappers ============

function getStatusFromIssue(
  issue: VibeCheckSliceState['stage3']['items'][number],
  reposWithCopilotPRs: string[]
): PipelineStatus {
  const repo = issue.repo || ''
  if (reposWithCopilotPRs.includes(repo)) return 'processing'
  const hasCopilotAssigned = issue.assignees?.some(a => a.login.toLowerCase().includes('copilot'))
  if (hasCopilotAssigned) return 'processing'
  return 'pending'
}

function getStatusFromPR(pr: VibeCheckSliceState['stage4']['items'][number]): PipelineStatus {
  if (pr.reviewDecision === 'APPROVED') return 'ready'
  if (isPRReady(pr)) return 'waiting_for_review'
  return 'processing'
}

function vibecheckItemMapper(state: PipelineState): PipelineItem[] {
  const items: PipelineItem[] = []

  for (const issue of state.stage3.items) {
    const severity = getSeverityFromLabels(issue.labels)
    items.push({
      id: `issue-${issue.repo}-${issue.number}`,
      type: 'vibecheck',
      repo: issue.repo || '',
      identifier: `#${issue.number}`,
      currentStage: 3,
      totalStages: 4,
      stageName: `Assign (${severity})`,
      status: getStatusFromIssue(issue, state.stage3.reposWithCopilotPRs),
      createdAt: issue.createdAt,
      updatedAt: issue.updatedAt || issue.createdAt,
      data: issue
    })
  }

  for (const pr of state.stage4.items) {
    items.push({
      id: `pr-${pr.repo}-${pr.number}`,
      type: 'vibecheck',
      repo: pr.repo || '',
      identifier: `PR #${pr.number}`,
      currentStage: 4,
      totalStages: 4,
      stageName: 'Review',
      status: getStatusFromPR(pr),
      createdAt: pr.createdAt,
      updatedAt: pr.updatedAt || pr.createdAt,
      data: pr
    })
  }

  return items
}

registerPipelineItemProvider('vibecheck', vibecheckItemMapper)

function ossItemMapper(state: PipelineState): PipelineItem[] {
  const items: PipelineItem[] = []

  for (const assignment of state.ossStage3.items) {
    items.push({
      id: `oss-assign-${assignment.originSlug}-${assignment.issueNumber}`,
      type: 'oss',
      repo: assignment.originSlug,
      identifier: `#${assignment.issueNumber}`,
      currentStage: 3,
      totalStages: 5,
      stageName: 'Fork & Assign',
      status: 'processing',
      createdAt: assignment.assignedAt,
      updatedAt: assignment.assignedAt,
      data: assignment
    })
  }

  for (const pr of state.ossStage4.items) {
    items.push({
      id: `oss-pr-${pr.repo}-${pr.number}`,
      type: 'oss',
      repo: pr.originSlug,
      identifier: `PR #${pr.number}`,
      currentStage: 4,
      totalStages: 5,
      stageName: 'Review on Fork',
      status: pr.reviewDecision === 'APPROVED' ? 'ready' : 'waiting_for_review',
      createdAt: pr.createdAt,
      updatedAt: pr.createdAt,
      data: pr
    })
  }

  for (const item of state.ossStage5.items) {
    items.push({
      id: `oss-submit-${item.originSlug}-${item.branch}`,
      type: 'oss',
      repo: item.originSlug,
      identifier: item.branch,
      currentStage: 5,
      totalStages: 5,
      stageName: 'Submit Upstream',
      status: 'ready',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      data: item
    })
  }

  return items
}

registerPipelineItemProvider('oss', ossItemMapper)

// ============ Store ============

export const usePipelineStore = create<PipelineState>((set, get) => ({
  // Slice state + actions
  ...createVibeCheckSlice<PipelineState>(set, get),
  ...createOSSSlice<PipelineState>(set, get),
  ...createUISlice<PipelineState>(set, get),
  ...createFilterSlice<PipelineState>(set, get),

  // Pipeline items (derived)
  pipelineItems: [],

  refreshPipelineItems: () => {
    const state = get()
    const items: PipelineItem[] = []

    for (const mapper of pipelineItemProviders.values()) {
      items.push(...mapper(state))
    }

    items.sort((a, b) => {
      const statusOrder: Record<PipelineStatus, number> = {
        waiting_for_review: 0,
        ready: 1,
        processing: 2,
        pending: 3,
        completed: 4,
        failed: 5
      }
      const statusDiff = statusOrder[a.status] - statusOrder[b.status]
      if (statusDiff !== 0) return statusDiff
      return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
    })

    set({ pipelineItems: items })
  }
}))

// ============ Selectors ============

export const selectReviewQueueCount = (state: PipelineState) =>
  state.pipelineItems.filter(item => item.status === 'waiting_for_review').length

export const selectIsLoading = (state: PipelineState) =>
  state.stage1.loading || state.stage2.loading || state.stage3.loading || state.stage4.loading

export const selectIsOSSLoading = (state: PipelineState) =>
  state.ossStage1.loading ||
  state.ossStage2.loading ||
  state.ossPipelineRuns.loading ||
  state.ossRetrospectiveLogs.loading ||
  state.ossSubmittedPRs.loading

export function selectAllOSSRepos(state: PipelineState): string[] {
  const repos = new Set<string>()
  for (const t of state.ossStage1.items) {
    const slug = (t as RepoHealthTarget).slug
    if (slug) repos.add(hyphenatedToSlashed(slug))
  }
  for (const i of state.ossStage2.items) {
    if (i.repo) repos.add(i.repo)
  }
  for (const a of state.ossPipelineRuns.items) {
    if (a.originSlug) repos.add(a.originSlug)
  }
  for (const p of state.ossSubmittedPRs.items) {
    if (p.originSlug) repos.add(p.originSlug)
  }
  return Array.from(repos).sort()
}
