/**
 * API Types for VibeDispatch
 *
 * These types mirror the JSON responses from the Flask backend.
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
    | 'success'
    | 'failure'
    | 'cancelled'
    | 'skipped'
    | 'timed_out'
    | 'action_required'
    | null
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

// ============ Stage API Response Types ============

export interface Stage1Response {
  success: boolean
  repos: Stage1Repo[]
  owner: string
}

export interface Stage2Response {
  success: boolean
  repos: Stage2Repo[]
  owner: string
}

export interface Stage3Response {
  success: boolean
  issues: Issue[]
  labels: string[]
  repos_with_copilot_prs: string[]
  owner: string
}

export interface Stage4Response {
  success: boolean
  prs: PullRequest[]
  owner: string
}

export interface PRDetailsResponse {
  success: boolean
  pr?: PRDetails
  error?: string
}

// ============ Action Response Types ============

export interface ActionResponse {
  success: boolean
  message?: string
  error?: string
}

export interface WorkflowStatusResponse {
  success: boolean
  run?: WorkflowRun
  error?: string
}

export interface HealthCheckResponse {
  success: boolean
  status: 'healthy' | 'degraded' | 'unhealthy'
  owner: string
  api_version: string
}

export interface GlobalWorkflowRunsResponse {
  success: boolean
  runs: (WorkflowRun & { repo: string; vibecheck_installed: boolean })[]
  owner: string
}

// ============ Pipeline Item Types (for new UI) ============

export type PipelineStatus =
  | 'pending'
  | 'processing'
  | 'waiting_for_review'
  | 'ready'
  | 'completed'
  | 'failed'

export interface PipelineItem {
  id: string
  type: 'vibecheck' | 'investigate' | 'custom' | 'oss'
  repo: string
  identifier: string // e.g., "issue-42" or "pr-23"
  currentStage: number
  totalStages: number
  stageName: string
  status: PipelineStatus
  createdAt: string
  updatedAt: string
  // The underlying data (issue, PR, etc.)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: Issue | PullRequest | Record<string, any>
}

// ============ OSS Pipeline Types ============

export interface OSSTarget {
  slug: string
  health?: {
    maintainerHealthScore: number
    mergeAccessibilityScore: number
    availabilityScore: number
    overallViability: number
  }
  meta?: {
    stars: number
    language: string
    license: string
    openIssueCount: number
    hasContributing: boolean
  }
}

export interface ScoredIssue {
  id: string
  repo: string
  number: number
  title: string
  url: string
  cvs: number
  cvsTier: 'go' | 'likely' | 'maybe' | 'risky' | 'skip'
  lifecycleStage: string
  complexity: string
  labels: string[]
  commentCount: number
  assignees: string[]
  claimStatus: string
  createdAt: string
  dataCompleteness: 'full' | 'partial'
  repoKilled: boolean
}

export interface OSSAssignment {
  originSlug: string
  repo: string
  issueNumber: number
  forkIssueNumber: number
  forkIssueUrl: string
  assignedAt: string
}

export interface ForkPR {
  number: number
  title: string
  url: string
  repo: string
  originSlug: string
  headRefName: string
  additions: number
  deletions: number
  changedFiles: number
  reviewDecision: string
  isDraft: boolean
  createdAt: string
}

export interface ReadyToSubmit {
  originSlug: string
  repo: string
  branch: string
  title: string
  baseBranch: string
}

export interface SubmittedPR {
  originSlug: string
  prUrl: string
  title: string
  state: string
  submittedAt: string
}

// ============ OSS API Response Types ============

export interface OSSBaseResponse {
  success: boolean
  owner: string
}

export interface OSSStage1Response extends OSSBaseResponse {
  targets: OSSTarget[]
}

export interface OSSStage2Response extends OSSBaseResponse {
  issues: ScoredIssue[]
}

export interface OSSStage3Response extends OSSBaseResponse {
  assignments: OSSAssignment[]
}

export interface OSSStage4Response extends OSSBaseResponse {
  prs: ForkPR[]
}

export interface OSSStage5Response extends OSSBaseResponse {
  ready: ReadyToSubmit[]
}

export interface OSSStage5TrackingResponse extends OSSBaseResponse {
  submitted: SubmittedPR[]
}

export interface OSSForkAssignResponse extends OSSBaseResponse {
  fork_issue_url?: string
  already_assigned?: boolean
  error?: string
}

export interface OSSSubmitResponse extends OSSBaseResponse {
  pr_url?: string
  error?: string
}
