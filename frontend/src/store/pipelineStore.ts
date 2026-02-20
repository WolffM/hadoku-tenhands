/**
 * Pipeline Store
 *
 * Central state management for pipeline items using Zustand.
 */

import { create } from 'zustand'
import type {
  Issue,
  PipelineItem,
  PipelineStatus,
  PullRequest,
  Stage1Repo,
  Stage2Repo,
  OSSTarget,
  ScoredIssue,
  OSSAssignment,
  ForkPR,
  ReadyToSubmit
} from '../api/types'
import {
  getStage1Repos,
  getStage2Repos,
  getStage3Issues,
  getStage4PRs,
  getOSSTargets,
  getOSSScoredIssues,
  getOSSAssigned,
  getOSSForkPRs,
  getOSSReadyToSubmit
} from '../api/endpoints'
import { isPRReady, getSeverityFromLabels, getErrorMessage } from '../utils'

// ============ Types ============

export type ViewType = 'list' | 'review' | 'health' | 'oss'

export interface LogEntry {
  id: string
  timestamp: Date
  message: string
  type: 'info' | 'success' | 'error' | 'warning'
}

interface StageData<T> {
  items: T[]
  loading: boolean
  error: string | null
  lastFetched: Date | null
}

interface PipelineState {
  // Current view
  activeView: ViewType

  // Owner (GitHub username)
  owner: string | null

  // Stage data
  stage1: StageData<Stage1Repo>
  stage2: StageData<Stage2Repo>
  stage3: StageData<Issue> & {
    labels: string[]
    reposWithCopilotPRs: string[]
  }
  stage4: StageData<PullRequest>

  // OSS stage data
  ossStage1: StageData<OSSTarget>
  ossStage2: StageData<ScoredIssue>
  ossStage3: StageData<OSSAssignment>
  ossStage4: StageData<ForkPR>
  ossStage5: StageData<ReadyToSubmit>

  // Pipeline items (derived from stage data)
  pipelineItems: PipelineItem[]

  // Expanded rows
  expandedRows: Set<string>

  // Selection state (for batch operations)
  selectedItems: Set<string>

  // Progress log
  logs: LogEntry[]

  // Actions
  setActiveView: (view: ViewType) => void
  setOwner: (owner: string) => void
  loadStage1: () => Promise<void>
  loadStage2: () => Promise<void>
  loadStage3: () => Promise<void>
  loadStage4: () => Promise<void>
  loadAllStages: () => Promise<void>
  toggleRowExpanded: (id: string) => void
  toggleItemSelected: (id: string) => void
  selectAll: () => void
  selectNone: () => void
  addLog: (message: string, type: LogEntry['type']) => void
  clearLogs: () => void
  refreshPipelineItems: () => void
  removeStage1Repo: (repoName: string) => void
  markStage2RepoTriggered: (repoName: string) => void
  removeStage3Issue: (repo: string, issueNumber: number) => void
  removeStage4PR: (repo: string, prNumber: number) => void

  // OSS actions
  loadOSSStage1: () => Promise<void>
  loadOSSStage2: () => Promise<void>
  loadOSSStage3: () => Promise<void>
  loadOSSStage4: () => Promise<void>
  loadOSSStage5: () => Promise<void>
  loadAllOSSStages: () => Promise<void>
  removeOSSAssignment: (originSlug: string, issueNumber: number) => void
  removeOSSForkPR: (repo: string, prNumber: number) => void
  removeOSSReadyToSubmit: (originSlug: string, branch: string) => void
}

// ============ Helpers ============

function createLogEntry(message: string, type: LogEntry['type'] = 'info'): LogEntry {
  return {
    id: `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    timestamp: new Date(),
    message,
    type
  }
}

function getStatusFromIssue(issue: Issue, reposWithCopilotPRs: string[]): PipelineStatus {
  const repo = issue.repo || ''
  // If repo has an active Copilot PR, it's processing
  if (reposWithCopilotPRs.includes(repo)) {
    return 'processing'
  }
  // If issue has Copilot assigned, it's processing
  const hasCopilotAssigned = issue.assignees?.some(a => a.login.toLowerCase().includes('copilot'))
  if (hasCopilotAssigned) {
    return 'processing'
  }
  // Otherwise pending assignment (not waiting_for_review - that's for PRs)
  return 'pending'
}

function getStatusFromPR(pr: PullRequest): PipelineStatus {
  // Already approved - ready to merge
  if (pr.reviewDecision === 'APPROVED') {
    return 'ready'
  }

  // Check if PR is ready for review using Stage4 logic
  if (isPRReady(pr)) {
    return 'waiting_for_review'
  }

  // Not ready yet - still in progress
  return 'processing'
}

// ============ Stage Loader Factory ============

interface StageLoaderConfig<R> {
  stageKey:
    | 'stage1'
    | 'stage2'
    | 'stage3'
    | 'stage4'
    | 'ossStage1'
    | 'ossStage2'
    | 'ossStage3'
    | 'ossStage4'
    | 'ossStage5'
  fetchFn: () => Promise<R>
  mapResponse: (response: R) => { items: unknown[]; extra?: Record<string, unknown> }
}

function createStageLoader<R extends { success: boolean; owner: string }>(
  config: StageLoaderConfig<R>,
  set: (fn: (state: PipelineState) => Partial<PipelineState>) => void,
  get: () => PipelineState
): () => Promise<void> {
  const { stageKey, fetchFn, mapResponse } = config
  return async () => {
    set(state => ({
      [stageKey]: { ...state[stageKey], loading: true, error: null }
    }))
    try {
      const response = await fetchFn()
      if (response.success) {
        const { items, extra } = mapResponse(response)
        set(state => ({
          owner: response.owner,
          [stageKey]: {
            ...state[stageKey],
            ...extra,
            items,
            loading: false,
            lastFetched: new Date()
          }
        }))
        get().refreshPipelineItems()
      } else {
        throw new Error(`Failed to load ${stageKey}`)
      }
    } catch (err) {
      set(state => ({
        [stageKey]: {
          ...state[stageKey],
          loading: false,
          error: getErrorMessage(err)
        }
      }))
    }
  }
}

// ============ Pipeline Item Registry ============

type ItemMapper = (state: PipelineState) => PipelineItem[]

const pipelineItemProviders = new Map<string, ItemMapper>()

export function registerPipelineItemProvider(type: string, mapper: ItemMapper) {
  pipelineItemProviders.set(type, mapper)
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

  // Stage 3 assignments → processing items
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

  // Stage 4 fork PRs → waiting_for_review or ready
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

  // Stage 5 ready-to-submit → ready items
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
  // Initial state
  activeView: 'list',
  owner: null,
  stage1: { items: [], loading: false, error: null, lastFetched: null },
  stage2: { items: [], loading: false, error: null, lastFetched: null },
  stage3: {
    items: [],
    loading: false,
    error: null,
    lastFetched: null,
    labels: [],
    reposWithCopilotPRs: []
  },
  stage4: { items: [], loading: false, error: null, lastFetched: null },
  ossStage1: { items: [], loading: false, error: null, lastFetched: null },
  ossStage2: { items: [], loading: false, error: null, lastFetched: null },
  ossStage3: { items: [], loading: false, error: null, lastFetched: null },
  ossStage4: { items: [], loading: false, error: null, lastFetched: null },
  ossStage5: { items: [], loading: false, error: null, lastFetched: null },
  pipelineItems: [],
  expandedRows: new Set(),
  selectedItems: new Set(),
  logs: [],

  // Actions
  setActiveView: view => set({ activeView: view }),

  setOwner: owner => set({ owner }),

  loadStage1: createStageLoader(
    {
      stageKey: 'stage1',
      fetchFn: getStage1Repos,
      mapResponse: r => ({ items: r.repos })
    },
    set,
    get
  ),

  loadStage2: createStageLoader(
    {
      stageKey: 'stage2',
      fetchFn: getStage2Repos,
      mapResponse: r => ({ items: r.repos })
    },
    set,
    get
  ),

  loadStage3: createStageLoader(
    {
      stageKey: 'stage3',
      fetchFn: getStage3Issues,
      mapResponse: r => ({
        items: r.issues,
        extra: { labels: r.labels, reposWithCopilotPRs: r.repos_with_copilot_prs }
      })
    },
    set,
    get
  ),

  loadStage4: createStageLoader(
    {
      stageKey: 'stage4',
      fetchFn: getStage4PRs,
      mapResponse: r => ({ items: r.prs })
    },
    set,
    get
  ),

  loadAllStages: async () => {
    // Load all stages in parallel
    await Promise.all([
      get().loadStage1(),
      get().loadStage2(),
      get().loadStage3(),
      get().loadStage4()
    ])
  },

  toggleRowExpanded: id => {
    set(state => {
      const newExpanded = new Set(state.expandedRows)
      if (newExpanded.has(id)) {
        newExpanded.delete(id)
      } else {
        newExpanded.add(id)
      }
      return { expandedRows: newExpanded }
    })
  },

  toggleItemSelected: id => {
    set(state => {
      const newSelected = new Set(state.selectedItems)
      if (newSelected.has(id)) {
        newSelected.delete(id)
      } else {
        newSelected.add(id)
      }
      return { selectedItems: newSelected }
    })
  },

  selectAll: () => {
    set(state => ({
      selectedItems: new Set(state.pipelineItems.map(item => item.id))
    }))
  },

  selectNone: () => {
    set({ selectedItems: new Set() })
  },

  addLog: (message, type = 'info') => {
    set(state => ({
      logs: [...state.logs, createLogEntry(message, type)]
    }))
  },

  clearLogs: () => {
    set({ logs: [] })
  },

  removeStage1Repo: (repoName: string) => {
    set(state => ({
      stage1: {
        ...state.stage1,
        items: state.stage1.items.filter(repo => repo.name !== repoName)
      }
    }))
  },

  markStage2RepoTriggered: (repoName: string) => {
    set(state => ({
      stage2: {
        ...state.stage2,
        items: state.stage2.items.map(repo => {
          if (repo.name === repoName) {
            // Create a new lastRun with 'queued' status to move out of recommended list
            return {
              ...repo,
              lastRun: {
                id: repo.lastRun?.id ?? 0,
                status: 'queued' as const,
                conclusion: null,
                createdAt: new Date().toISOString()
              },
              commitsSinceLastRun: 0
            }
          }
          return repo
        })
      }
    }))
  },

  removeStage3Issue: (repo: string, issueNumber: number) => {
    set(state => ({
      stage3: {
        ...state.stage3,
        items: state.stage3.items.filter(
          issue => !(issue.repo === repo && issue.number === issueNumber)
        ),
        // Add repo to reposWithCopilotPRs so other issues from this repo
        // are excluded from recommended (Copilot is now working on this repo)
        reposWithCopilotPRs: state.stage3.reposWithCopilotPRs.includes(repo)
          ? state.stage3.reposWithCopilotPRs
          : [...state.stage3.reposWithCopilotPRs, repo]
      }
    }))
    // Also refresh pipeline items to update the list view
    get().refreshPipelineItems()
  },

  removeStage4PR: (repo: string, prNumber: number) => {
    set(state => ({
      stage4: {
        ...state.stage4,
        items: state.stage4.items.filter(pr => !(pr.repo === repo && pr.number === prNumber))
      }
    }))
    // Also refresh pipeline items to update the list view
    get().refreshPipelineItems()
  },

  // OSS stage loaders
  loadOSSStage1: createStageLoader(
    { stageKey: 'ossStage1', fetchFn: getOSSTargets, mapResponse: r => ({ items: r.targets }) },
    set,
    get
  ),
  loadOSSStage2: createStageLoader(
    { stageKey: 'ossStage2', fetchFn: getOSSScoredIssues, mapResponse: r => ({ items: r.issues }) },
    set,
    get
  ),
  loadOSSStage3: createStageLoader(
    {
      stageKey: 'ossStage3',
      fetchFn: getOSSAssigned,
      mapResponse: r => ({ items: r.assignments })
    },
    set,
    get
  ),
  loadOSSStage4: createStageLoader(
    { stageKey: 'ossStage4', fetchFn: getOSSForkPRs, mapResponse: r => ({ items: r.prs }) },
    set,
    get
  ),
  loadOSSStage5: createStageLoader(
    { stageKey: 'ossStage5', fetchFn: getOSSReadyToSubmit, mapResponse: r => ({ items: r.ready }) },
    set,
    get
  ),

  loadAllOSSStages: async () => {
    await Promise.all([
      get().loadOSSStage1(),
      get().loadOSSStage2(),
      get().loadOSSStage3(),
      get().loadOSSStage4(),
      get().loadOSSStage5()
    ])
  },

  // OSS optimistic removers
  removeOSSAssignment: (originSlug: string, issueNumber: number) => {
    set(state => ({
      ossStage3: {
        ...state.ossStage3,
        items: state.ossStage3.items.filter(
          a => !(a.originSlug === originSlug && a.issueNumber === issueNumber)
        )
      }
    }))
    get().refreshPipelineItems()
  },

  removeOSSForkPR: (repo: string, prNumber: number) => {
    set(state => ({
      ossStage4: {
        ...state.ossStage4,
        items: state.ossStage4.items.filter(pr => !(pr.repo === repo && pr.number === prNumber))
      }
    }))
    get().refreshPipelineItems()
  },

  removeOSSReadyToSubmit: (originSlug: string, branch: string) => {
    set(state => ({
      ossStage5: {
        ...state.ossStage5,
        items: state.ossStage5.items.filter(
          item => !(item.originSlug === originSlug && item.branch === branch)
        )
      }
    }))
    get().refreshPipelineItems()
  },

  refreshPipelineItems: () => {
    const state = get()
    const items: PipelineItem[] = []

    for (const mapper of pipelineItemProviders.values()) {
      items.push(...mapper(state))
    }

    // Sort by status (waiting_for_review first) then by date
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
  state.ossStage3.loading ||
  state.ossStage4.loading ||
  state.ossStage5.loading
