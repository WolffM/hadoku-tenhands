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
 *
 * The exception is the merged PR itself: `mergedIds` records it the moment
 * GitHub confirms the merge, so its row goes away immediately instead of
 * flickering back to a clickable "Merge" for the length of the status reload.
 * That entry is dropped again as soon as a reload stops listing the PR, so the
 * set only ever holds PRs the backend has yet to catch up on.
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
  /** `repo#number` of PRs merged this session but still listed by the backend. */
  mergedIds: string[]

  loadStatus: () => Promise<void>
  merge: (repo: string, number: number) => Promise<void>
}

const prId = (pr: { repo: string; number: number }) => `${pr.repo}#${pr.number}`

export const useTaskAutoStore = create<TaskAutoState>((set, get) => ({
  status: null,
  loading: false,
  error: null,
  lastFetched: null,
  merging: null,
  mergeError: null,
  mergedIds: [],

  loadStatus: async () => {
    set(s => ({ ...s, loading: true, error: null }))
    try {
      const status = await getTaskAutoStatus()
      const listed = new Set(status.boards.flatMap(b => b.prs ?? []).map(prId))
      set(s => ({
        ...s,
        status,
        loading: false,
        error: null,
        lastFetched: new Date(),
        mergedIds: s.mergedIds.filter(id => listed.has(id))
      }))
    } catch (err) {
      set(s => ({ ...s, loading: false, error: getErrorMessage(err) }))
    }
  },

  merge: async (repo: string, number: number) => {
    const id = prId({ repo, number })
    set(s => ({ ...s, merging: id, mergeError: null }))
    try {
      await mergeTaskAutoPR(repo, number)
      set(s => ({
        ...s,
        merging: null,
        mergedIds: s.mergedIds.includes(id) ? s.mergedIds : [...s.mergedIds, id]
      }))
      await get().loadStatus()
    } catch (err) {
      set(s => ({ ...s, merging: null, mergeError: getErrorMessage(err) }))
    }
  }
}))
