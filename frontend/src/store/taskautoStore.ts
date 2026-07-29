/**
 * Task Automation (hadoku-task-automation) Store
 *
 * Standalone Zustand store for the board-driven pipeline, kept separate from
 * `usePipelineStore` for the same reason `temporalStore` is: the data shape
 * here is boards → lanes → tasks, which does not fit the `PipelineItem`
 * derivation model used by vibecheck + oss.
 *
 * Mirrors the async-action + error-handling pattern from `temporalStore.ts`.
 *
 * One deliberate asymmetry: `merge` reloads status on success rather than
 * patching the PR out of local state. A merge changes the task's lane on the
 * board too, and guessing the new lane here would put the UI a step ahead of
 * the pipeline that actually owns that transition.
 */

import { create } from 'zustand'
import { getTaskAutoStatus, mergeTaskAutoPR } from '../api/endpoints'
import type { TaskAutoStatus } from '../api/types'
import { getErrorMessage } from '../utils'

export interface TaskAutoState {
  status: TaskAutoStatus | null
  loading: boolean
  error: string | null
  lastFetched: Date | null

  /** Repo/number of the PR currently being merged, so one button spins. */
  merging: string | null
  mergeError: string | null

  loadStatus: () => Promise<void>
  merge: (repo: string, number: number) => Promise<void>
}

export const useTaskAutoStore = create<TaskAutoState>((set, get) => ({
  status: null,
  loading: false,
  error: null,
  lastFetched: null,
  merging: null,
  mergeError: null,

  loadStatus: async () => {
    set(s => ({ ...s, loading: true, error: null }))
    try {
      const status = await getTaskAutoStatus()
      set({ status, loading: false, error: null, lastFetched: new Date() })
    } catch (err) {
      set(s => ({ ...s, loading: false, error: getErrorMessage(err) }))
    }
  },

  merge: async (repo: string, number: number) => {
    set(s => ({ ...s, merging: `${repo}#${number}`, mergeError: null }))
    try {
      await mergeTaskAutoPR(repo, number)
      set(s => ({ ...s, merging: null }))
      await get().loadStatus()
    } catch (err) {
      set(s => ({ ...s, merging: null, mergeError: getErrorMessage(err) }))
    }
  }
}))
