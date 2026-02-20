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
  Stage2Repo
} from '../api/types'
import { getStage1Repos, getStage2Repos, getStage3Issues, getStage4PRs } from '../api/endpoints'
import { isPRReady } from '../utils'

// ============ Types ============

export type ViewType = 'list' | 'review' | 'health'

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

function getSeverityFromLabels(labels: { name: string }[]): string {
  const labelNames = labels.map(l => l.name.toLowerCase())
  if (labelNames.some(l => l.includes('severity:critical'))) return 'critical'
  if (labelNames.some(l => l.includes('severity:high'))) return 'high'
  if (labelNames.some(l => l.includes('severity:medium'))) return 'medium'
  if (labelNames.some(l => l.includes('severity:low'))) return 'low'
  return 'unknown'
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
  pipelineItems: [],
  expandedRows: new Set(),
  selectedItems: new Set(),
  logs: [],

  // Actions
  setActiveView: view => set({ activeView: view }),

  setOwner: owner => set({ owner }),

  loadStage1: async () => {
    set(state => ({
      stage1: { ...state.stage1, loading: true, error: null }
    }))
    try {
      const response = await getStage1Repos()
      if (response.success) {
        set(state => ({
          owner: response.owner,
          stage1: {
            ...state.stage1,
            items: response.repos,
            loading: false,
            lastFetched: new Date()
          }
        }))
        get().refreshPipelineItems()
      } else {
        throw new Error('Failed to load stage 1 repos')
      }
    } catch (err) {
      set(state => ({
        stage1: {
          ...state.stage1,
          loading: false,
          error: err instanceof Error ? err.message : 'Unknown error'
        }
      }))
    }
  },

  loadStage2: async () => {
    set(state => ({
      stage2: { ...state.stage2, loading: true, error: null }
    }))
    try {
      const response = await getStage2Repos()
      if (response.success) {
        set(state => ({
          owner: response.owner,
          stage2: {
            ...state.stage2,
            items: response.repos,
            loading: false,
            lastFetched: new Date()
          }
        }))
        get().refreshPipelineItems()
      } else {
        throw new Error('Failed to load stage 2 repos')
      }
    } catch (err) {
      set(state => ({
        stage2: {
          ...state.stage2,
          loading: false,
          error: err instanceof Error ? err.message : 'Unknown error'
        }
      }))
    }
  },

  loadStage3: async () => {
    set(state => ({
      stage3: { ...state.stage3, loading: true, error: null }
    }))
    try {
      const response = await getStage3Issues()
      if (response.success) {
        set(state => ({
          owner: response.owner,
          stage3: {
            ...state.stage3,
            items: response.issues,
            labels: response.labels,
            reposWithCopilotPRs: response.repos_with_copilot_prs,
            loading: false,
            lastFetched: new Date()
          }
        }))
        get().refreshPipelineItems()
      } else {
        throw new Error('Failed to load stage 3 issues')
      }
    } catch (err) {
      set(state => ({
        stage3: {
          ...state.stage3,
          loading: false,
          error: err instanceof Error ? err.message : 'Unknown error'
        }
      }))
    }
  },

  loadStage4: async () => {
    set(state => ({
      stage4: { ...state.stage4, loading: true, error: null }
    }))
    try {
      const response = await getStage4PRs()
      if (response.success) {
        set(state => ({
          owner: response.owner,
          stage4: {
            ...state.stage4,
            items: response.prs,
            loading: false,
            lastFetched: new Date()
          }
        }))
        get().refreshPipelineItems()
      } else {
        throw new Error('Failed to load stage 4 PRs')
      }
    } catch (err) {
      set(state => ({
        stage4: {
          ...state.stage4,
          loading: false,
          error: err instanceof Error ? err.message : 'Unknown error'
        }
      }))
    }
  },

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

  refreshPipelineItems: () => {
    const state = get()
    const items: PipelineItem[] = []

    // Add stage 3 issues as pipeline items
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

    // Add stage 4 PRs as pipeline items
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
