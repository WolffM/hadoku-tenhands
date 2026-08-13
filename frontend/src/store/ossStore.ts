/**
 * OSS Store Slice
 *
 * State and loaders for OSS targets, scored issues, pipeline runs,
 * retrospectives, and submitted PRs.
 */

import type {
  OSSTarget,
  ScoredIssue,
  PipelineAssignment,
  RetrospectiveEntry,
  SubmittedPR
} from '../api/types'
import {
  getOSSTargets,
  getOSSScoredIssues,
  getPipelineStatus,
  getRetrospectiveLogs,
  pollSubmittedPRs
} from '../api/endpoints'
import { getErrorMessage, normalizePipelineAssignment, normalizeSubmittedPR } from '../utils'
import type { StageData } from './vibeCheckStore'

// ============ Types (re-exported for consumers) ============

export interface OSSSliceState {
  // OSS stage data
  ossStage1: StageData<OSSTarget>
  ossStage2: StageData<ScoredIssue>

  // OSS pipeline redesign data
  ossPipelineRuns: StageData<PipelineAssignment>
  ossRetrospectiveLogs: StageData<RetrospectiveEntry>
  ossSubmittedPRs: StageData<SubmittedPR>

  // Actions
  loadOSSStage1: () => Promise<void>
  loadOSSStage2: () => Promise<void>
  loadAllOSSStages: () => Promise<void>
  loadOSSPipelineRuns: () => Promise<void>
  loadOSSRetrospectiveLogs: () => Promise<void>
  loadOSSSubmittedPRs: () => Promise<void>
}

// ============ Slice Creator ============

export function createOSSSlice<S extends OSSSliceState>(
  set: (fn: (state: S) => Partial<S>) => void,
  get: () => S
): OSSSliceState {
  return {
    ossStage1: { items: [], loading: false, error: null, lastFetched: null },
    ossStage2: { items: [], loading: false, error: null, lastFetched: null },
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

    loadAllOSSStages: async () => {
      await Promise.all([
        get().loadOSSStage1(),
        get().loadOSSStage2(),
        get().loadOSSPipelineRuns(),
        get().loadOSSRetrospectiveLogs(),
        get().loadOSSSubmittedPRs()
      ])
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
