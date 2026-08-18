/**
 * Shared API primitives: the GitHub entities every pipeline speaks in.
 *
 * Nothing here is specific to one pipeline — if a type is only ever used by
 * OSS, temporal or task-automation, it belongs in that module instead.
 */

// ============ Base Types ============

export interface User {
  login: string
  avatarUrl?: string
}

export interface Label {
  name: string
  color?: string
  description?: string
}

// ============ Repository Types ============

export interface Repo {
  name: string
  description?: string
  isPrivate: boolean
  vibecheck_installed?: boolean
}

// Repos that need vibecheck installed
export type Stage1Repo = Repo

export interface WorkflowRun {
  id: number
  name?: string
  workflowName?: string
  status: 'queued' | 'in_progress' | 'completed' | 'waiting' | 'requested' | 'pending'
  conclusion?:
    'success' | 'failure' | 'cancelled' | 'skipped' | 'timed_out' | 'action_required' | null
  createdAt: string
  updatedAt?: string
  url?: string
  headBranch?: string
  headSha?: string
}

export interface Stage2Repo extends Repo {
  lastRun: WorkflowRun | null
  commitsSinceLastRun: number
}

// ============ Issue Types ============

export interface Issue {
  number: number
  title: string
  body?: string
  state: 'open' | 'closed'
  url: string
  createdAt: string
  updatedAt?: string
  labels: Label[]
  assignees: User[]
  repo?: string // Added by backend when fetching across repos
}

export type SeverityLevel = 'critical' | 'high' | 'medium' | 'low' | 'unknown'

// ============ Pull Request Types ============

export interface PullRequest {
  number: number
  title: string
  body?: string
  state: 'open' | 'closed' | 'merged'
  url: string
  createdAt: string
  updatedAt?: string
  author: User | null
  isDraft: boolean
  headRefName: string
  baseRefName: string
  reviewDecision?: 'APPROVED' | 'CHANGES_REQUESTED' | 'REVIEW_REQUIRED' | null
  labels?: Label[]
  assignees?: User[]
  repo?: string // Added by backend when fetching across repos
  copilotCompleted?: boolean | null // null = not a Copilot PR
}

export interface PRFile {
  path: string
  additions: number
  deletions: number
  status: 'added' | 'modified' | 'removed' | 'renamed'
}

export interface PRDetails extends PullRequest {
  files?: PRFile[]
  commits?: number
  additions: number
  deletions: number
  changedFiles: number
  diff?: string
}
