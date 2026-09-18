/**
 * hadoku-task-automation: boards, tasks, claims, and the PRs they generate.
 */

import type { PRFile, User } from './common'

// ============ Task Automation (hadoku-task-automation) ============

export interface TaskAutoPR {
  repo: string
  number: number
  title: string
  url: string
  branch: string
  /** ULID of the task this PR was generated from — pairs a diff to its plan. */
  taskId: string
  additions: number
  deletions: number
  changedFiles: number
  mergeState: string
  isDraft: boolean
  checks: 'passing' | 'failing' | 'pending' | 'none'
  updatedAt: string
}

export interface TaskAutoMetrics {
  /** Agent seconds only — CI and human thinking time never appear here. */
  agent_s?: number
  plan_s?: number
  plan_passes?: number
  implement_s?: number
  implement_runs?: number
  finished_lane?: string
}

export interface TaskAutoTask {
  id: string
  title: string
  claimed: boolean
  updatedAt: string
  hasPlan: boolean
  /** Two lane tags — resolves to no lane, so the scheduler cannot see it. */
  stuck: boolean
  metrics?: TaskAutoMetrics
}

/** One claim the pipeline took on a task, from the board's claim log. */
export interface TaskAutoClaim {
  agentId: string
  claimedAt: string
  endedAt: string
  /** `release` | `cancel` | `expire` — how the claim ended. */
  endedBy: string
  /** What that turn produced, e.g. `plan:questions`, `pr-open:88`. */
  outcome: string
}

/** A PR for one task, including merged and closed ones. */
export interface TaskAutoTaskPR extends TaskAutoPR {
  /** `OPEN` | `MERGED` | `CLOSED`. */
  state: string
  mergedAt: string
  createdAt: string
}

export interface TaskAutoTaskDetail {
  success: boolean
  board: { handle: string; name: string; repo: string }
  task: {
    id: string
    title: string
    notes: string
    lane: string
    laneTags: string[]
    tag: string
    claimed: boolean
    state: string
    createdAt: string
    updatedAt: string
    branch: string
    metrics: TaskAutoMetrics
  }
  /** Oldest first — the order a timeline is read. */
  history: TaskAutoClaim[]
  prs: TaskAutoTaskPR[]
}

export interface TaskAutoBoard {
  handle: string
  name: string
  repo: string
  schemaId?: string
  schemaVersion?: number
  lanes: Record<string, TaskAutoTask[]>
  counts: Record<string, number>
  prs: TaskAutoPR[]
  error?: string
}

export interface TaskAutoStatus {
  success: boolean
  boards: TaskAutoBoard[]
  running: (TaskAutoTask & { board: string; repo: string; lane: string })[]
  laneOrder: string[]
  prCount: number
}

/** One taskauto PR's diff, plus the task it came from — for in-app review.
 *  Flat envelope: the fields sit alongside `success`, like every taskauto route. */
export interface TaskAutoPRDetails {
  success: boolean
  number: number
  title: string
  body?: string
  author: User | null
  createdAt: string
  headRefName: string
  baseRefName: string
  files?: PRFile[]
  commits?: number
  state: string
  url: string
  isDraft: boolean
  additions: number
  deletions: number
  changedFiles: number
  diff: string
  repo: string
  /** First 12 chars of the ULID of the task this PR was generated from. */
  taskId: string
  taskTitle: string
  /** The task's `notes` — the plan the human approved, in the pipeline's own markdown. */
  taskNotes: string
}
