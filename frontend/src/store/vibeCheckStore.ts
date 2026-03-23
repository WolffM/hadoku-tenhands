/**
 * VibeCheck Store Slice
 *
 * State and loaders for Stage1Repo, Stage2Repo, Issues (stage3), and PullRequests (stage4).
 */

import type { Stage1Repo, Stage2Repo, Issue, PullRequest } from '../api/types'
import { getStage1Repos, getStage2Repos, getStage3Issues, getStage4PRs } from '../api/endpoints'
import { getErrorMessage } from '../utils'

// ============ Types (re-exported for consumers) ============

export interface StageData<T> {
  items: T[]
  loading: boolean
  error: string | null
  lastFetched: Date | null
}

export interface VibeCheckSliceState {
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

  // Actions
  setOwner: (owner: string) => void
  loadStage1: () => Promise<void>
  loadStage2: () => Promise<void>
  loadStage3: () => Promise<void>
  loadStage4: () => Promise<void>
  loadAllStages: () => Promise<void>
  removeStage1Repo: (repoName: string) => void
  markStage2RepoTriggered: (repoName: string) => void
  removeStage3Issue: (repo: string, issueNumber: number) => void
  removeStage4PR: (repo: string, prNumber: number) => void
}

// ============ Slice Dependencies ============

export interface WithRefresh {
  refreshPipelineItems: () => void
}

// ============ Slice Creator ============

export function createVibeCheckSlice<S extends VibeCheckSliceState & WithRefresh>(
  set: (fn: (state: S) => Partial<S>) => void,
  get: () => S
): VibeCheckSliceState {
  return {
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

    setOwner: (owner: string) => set(_s => ({ owner }) as Partial<S>),

    loadStage1: async () => {
      set(s => ({ stage1: { ...s.stage1, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getStage1Repos()
        if (response.success) {
          set(
            s =>
              ({
                owner: response.owner,
                stage1: {
                  ...s.stage1,
                  items: response.repos,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load stage1')
        }
      } catch (err) {
        set(
          s =>
            ({
              stage1: { ...s.stage1, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadStage2: async () => {
      set(s => ({ stage2: { ...s.stage2, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getStage2Repos()
        if (response.success) {
          set(
            s =>
              ({
                owner: response.owner,
                stage2: {
                  ...s.stage2,
                  items: response.repos,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load stage2')
        }
      } catch (err) {
        set(
          s =>
            ({
              stage2: { ...s.stage2, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadStage3: async () => {
      set(s => ({ stage3: { ...s.stage3, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getStage3Issues()
        if (response.success) {
          set(
            s =>
              ({
                owner: response.owner,
                stage3: {
                  ...s.stage3,
                  items: response.issues,
                  labels: response.labels,
                  reposWithCopilotPRs: response.repos_with_copilot_prs,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load stage3')
        }
      } catch (err) {
        set(
          s =>
            ({
              stage3: { ...s.stage3, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadStage4: async () => {
      set(s => ({ stage4: { ...s.stage4, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getStage4PRs()
        if (response.success) {
          set(
            s =>
              ({
                owner: response.owner,
                stage4: {
                  ...s.stage4,
                  items: response.prs,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load stage4')
        }
      } catch (err) {
        set(
          s =>
            ({
              stage4: { ...s.stage4, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadAllStages: async () => {
      await Promise.all([
        get().loadStage1(),
        get().loadStage2(),
        get().loadStage3(),
        get().loadStage4()
      ])
    },

    removeStage1Repo: (repoName: string) => {
      set(
        s =>
          ({
            stage1: { ...s.stage1, items: s.stage1.items.filter(repo => repo.name !== repoName) }
          }) as Partial<S>
      )
    },

    markStage2RepoTriggered: (repoName: string) => {
      set(
        s =>
          ({
            stage2: {
              ...s.stage2,
              items: s.stage2.items.map(repo => {
                if (repo.name === repoName) {
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
          }) as Partial<S>
      )
    },

    removeStage3Issue: (repo: string, issueNumber: number) => {
      set(
        s =>
          ({
            stage3: {
              ...s.stage3,
              items: s.stage3.items.filter(
                issue => !(issue.repo === repo && issue.number === issueNumber)
              ),
              reposWithCopilotPRs: s.stage3.reposWithCopilotPRs.includes(repo)
                ? s.stage3.reposWithCopilotPRs
                : [...s.stage3.reposWithCopilotPRs, repo]
            }
          }) as Partial<S>
      )
      get().refreshPipelineItems()
    },

    removeStage4PR: (repo: string, prNumber: number) => {
      set(
        s =>
          ({
            stage4: {
              ...s.stage4,
              items: s.stage4.items.filter(pr => !(pr.repo === repo && pr.number === prNumber))
            }
          }) as Partial<S>
      )
      get().refreshPipelineItems()
    }
  }
}
