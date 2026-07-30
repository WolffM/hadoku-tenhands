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
import { getTaskAutoStatus, getTaskAutoTask, mergeTaskAutoPR } from '../api/endpoints'
import type { TaskAutoStatus, TaskAutoTaskDetail } from '../api/types'
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

  /** The task whose detail is open, or null. Board handle + task id. */
  openTask: { board: string; taskId: string } | null
  taskDetail: TaskAutoTaskDetail | null
  taskLoading: boolean
  taskError: string | null

  loadStatus: () => Promise<void>
  merge: (repo: string, number: number, auto?: boolean) => Promise<void>
  showTask: (board: string, taskId: string) => Promise<void>
  hideTask: () => void
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
  openTask: null,
  taskDetail: null,
  taskLoading: false,
  taskError: null,

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

  merge: async (repo: string, number: number, auto = false) => {
    const id = prId({ repo, number })
    set(s => ({ ...s, merging: id, mergeError: null }))
    try {
      await mergeTaskAutoPR(repo, number, auto)
      set(s => ({
        ...s,
        merging: null,
        // Only a completed merge earns a hidden row. An auto-merge is still an
        // OPEN pull request waiting on CI — hiding it would tell the user the
        // work landed when it may yet fail and need them back.
        mergedIds: auto || s.mergedIds.includes(id) ? s.mergedIds : [...s.mergedIds, id]
      }))
      await get().loadStatus()
    } catch (err) {
      set(s => ({ ...s, merging: null, mergeError: getErrorMessage(err) }))
    }
  },

  showTask: async (board: string, taskId: string) => {
    set(s => ({
      ...s,
      openTask: { board, taskId },
      // Drop the previous task's detail rather than showing it under the new
      // title while this one loads.
      taskDetail: null,
      taskLoading: true,
      taskError: null
    }))
    try {
      const detail = await getTaskAutoTask(board, taskId)
      // A second click while the first was in flight wins; discard the
      // late answer instead of overwriting what the user is now looking at.
      if (get().openTask?.taskId !== taskId) return
      set(s => ({ ...s, taskDetail: detail, taskLoading: false }))
    } catch (err) {
      if (get().openTask?.taskId !== taskId) return
      set(s => ({ ...s, taskLoading: false, taskError: getErrorMessage(err) }))
    }
  },

  hideTask: () =>
    set(s => ({
      ...s,
      openTask: null,
      taskDetail: null,
      taskLoading: false,
      taskError: null
    }))
}))
