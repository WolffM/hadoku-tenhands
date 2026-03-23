/**
 * OSS Store Slice
 *
 * State and loaders for OSS stages 1-5, pipeline runs, retrospectives, and submitted PRs.
 */

import type {
  OSSTarget,
  ScoredIssue,
  OSSAssignment,
  ForkPR,
  ReadyToSubmit,
  PipelineAssignment,
  RetrospectiveEntry,
  SubmittedPR
} from '../api/types'
import {
  getOSSTargets,
  getOSSScoredIssues,
  getOSSAssigned,
  getOSSForkPRs,
  getOSSReadyToSubmit,
  getPipelineStatus,
  getRetrospectiveLogs,
  pollSubmittedPRs
} from '../api/endpoints'
import { getErrorMessage, normalizePipelineAssignment, normalizeSubmittedPR } from '../utils'
import type { StageData, WithRefresh } from './vibeCheckStore'

// ============ Types (re-exported for consumers) ============

export interface OSSSliceState {
  // OSS stage data
  ossStage1: StageData<OSSTarget>
  ossStage2: StageData<ScoredIssue>
  ossStage3: StageData<OSSAssignment>
  ossStage4: StageData<ForkPR>
  ossStage5: StageData<ReadyToSubmit>

  // OSS pipeline redesign data
  ossPipelineRuns: StageData<PipelineAssignment>
  ossRetrospectiveLogs: StageData<RetrospectiveEntry>
  ossSubmittedPRs: StageData<SubmittedPR>

  // Actions
  loadOSSStage1: () => Promise<void>
  loadOSSStage2: () => Promise<void>
  loadOSSStage3: () => Promise<void>
  loadOSSStage4: () => Promise<void>
  loadOSSStage5: () => Promise<void>
  loadAllOSSStages: () => Promise<void>
  removeOSSForkPR: (repo: string, prNumber: number) => void
  removeOSSReadyToSubmit: (originSlug: string, branch: string) => void
  loadOSSPipelineRuns: () => Promise<void>
  loadOSSRetrospectiveLogs: () => Promise<void>
  loadOSSSubmittedPRs: () => Promise<void>
}

// ============ Slice Creator ============

export function createOSSSlice<S extends OSSSliceState & WithRefresh>(
  set: (fn: (state: S) => Partial<S>) => void,
  get: () => S
): OSSSliceState {
  return {
    ossStage1: { items: [], loading: false, error: null, lastFetched: null },
    ossStage2: { items: [], loading: false, error: null, lastFetched: null },
    ossStage3: { items: [], loading: false, error: null, lastFetched: null },
    ossStage4: { items: [], loading: false, error: null, lastFetched: null },
    ossStage5: { items: [], loading: false, error: null, lastFetched: null },
    ossPipelineRuns: { items: [], loading: false, error: null, lastFetched: null },
    ossRetrospectiveLogs: { items: [], loading: false, error: null, lastFetched: null },
    ossSubmittedPRs: { items: [], loading: false, error: null, lastFetched: null },

    loadOSSStage1: async () => {
      set(s => ({ ossStage1: { ...s.ossStage1, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getOSSTargets()
        if (response.success) {
          set(
            s =>
              ({
                ossStage1: {
                  ...s.ossStage1,
                  items: response.targets,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossStage1')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossStage1: { ...s.ossStage1, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadOSSStage2: async () => {
      set(s => ({ ossStage2: { ...s.ossStage2, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getOSSScoredIssues()
        if (response.success) {
          set(
            s =>
              ({
                ossStage2: {
                  ...s.ossStage2,
                  items: response.issues,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossStage2')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossStage2: { ...s.ossStage2, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadOSSStage3: async () => {
      set(s => ({ ossStage3: { ...s.ossStage3, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getOSSAssigned()
        if (response.success) {
          set(
            s =>
              ({
                ossStage3: {
                  ...s.ossStage3,
                  items: response.assignments,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossStage3')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossStage3: { ...s.ossStage3, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadOSSStage4: async () => {
      set(s => ({ ossStage4: { ...s.ossStage4, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getOSSForkPRs()
        if (response.success) {
          set(
            s =>
              ({
                ossStage4: {
                  ...s.ossStage4,
                  items: response.prs,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossStage4')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossStage4: { ...s.ossStage4, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadOSSStage5: async () => {
      set(s => ({ ossStage5: { ...s.ossStage5, loading: true, error: null } }) as Partial<S>)
      try {
        const response = await getOSSReadyToSubmit()
        if (response.success) {
          set(
            s =>
              ({
                ossStage5: {
                  ...s.ossStage5,
                  items: response.ready,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossStage5')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossStage5: { ...s.ossStage5, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadAllOSSStages: async () => {
      await Promise.all([
        get().loadOSSStage1(),
        get().loadOSSStage2(),
        get().loadOSSPipelineRuns(),
        get().loadOSSRetrospectiveLogs(),
        get().loadOSSSubmittedPRs()
      ])
    },

    removeOSSForkPR: (repo: string, prNumber: number) => {
      set(
        s =>
          ({
            ossStage4: {
              ...s.ossStage4,
              items: s.ossStage4.items.filter(pr => !(pr.repo === repo && pr.number === prNumber))
            }
          }) as Partial<S>
      )
      get().refreshPipelineItems()
    },

    removeOSSReadyToSubmit: (originSlug: string, branch: string) => {
      set(
        s =>
          ({
            ossStage5: {
              ...s.ossStage5,
              items: s.ossStage5.items.filter(
                item => !(item.originSlug === originSlug && item.branch === branch)
              )
            }
          }) as Partial<S>
      )
      get().refreshPipelineItems()
    },

    loadOSSPipelineRuns: async () => {
      set(
        s =>
          ({
            ossPipelineRuns: { ...s.ossPipelineRuns, loading: true, error: null }
          }) as Partial<S>
      )
      try {
        const response = await getPipelineStatus()
        if (response.success) {
          const items = (response.statuses || []).map(s =>
            normalizePipelineAssignment(s as unknown as Record<string, unknown>)
          )
          set(
            s =>
              ({
                ossPipelineRuns: {
                  ...s.ossPipelineRuns,
                  items,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossPipelineRuns')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossPipelineRuns: { ...s.ossPipelineRuns, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    },

    loadOSSRetrospectiveLogs: async () => {
      set(
        s =>
          ({
            ossRetrospectiveLogs: { ...s.ossRetrospectiveLogs, loading: true, error: null }
          }) as Partial<S>
      )
      try {
        const response = await getRetrospectiveLogs()
        if (response.success) {
          set(
            s =>
              ({
                ossRetrospectiveLogs: {
                  ...s.ossRetrospectiveLogs,
                  items: response.logs,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossRetrospectiveLogs')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossRetrospectiveLogs: {
                ...s.ossRetrospectiveLogs,
                loading: false,
                error: getErrorMessage(err)
              }
            }) as Partial<S>
        )
      }
    },

    loadOSSSubmittedPRs: async () => {
      set(
        s =>
          ({
            ossSubmittedPRs: { ...s.ossSubmittedPRs, loading: true, error: null }
          }) as Partial<S>
      )
      try {
        const response = await pollSubmittedPRs()
        if (response.success) {
          const items = (response.submitted || []).map(s =>
            normalizeSubmittedPR(s as unknown as Record<string, unknown>)
          )
          set(
            s =>
              ({
                ossSubmittedPRs: {
                  ...s.ossSubmittedPRs,
                  items,
                  loading: false,
                  lastFetched: new Date()
                }
              }) as Partial<S>
          )
          get().refreshPipelineItems()
        } else {
          throw new Error('Failed to load ossSubmittedPRs')
        }
      } catch (err) {
        set(
          s =>
            ({
              ossSubmittedPRs: { ...s.ossSubmittedPRs, loading: false, error: getErrorMessage(err) }
            }) as Partial<S>
        )
      }
    }
  }
}
