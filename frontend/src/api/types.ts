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
  apiVersion: string
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
  prNumber?: number
  title: string
  state: string
  reviewDecision?: string
  mergedAt?: string
  closedAt?: string
  lastPolledAt?: string
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

// ============ Dossier Types ============

export interface DossierSections {
  overview: string
  contributionRules: string
  successPatterns: string
  antiPatterns: string
  issueBoard: string
  environmentSetup: string
}

export interface Dossier {
  slug: string
  generatedAt: string
  sections: DossierSections
}

export interface OSSDossierResponse extends OSSBaseResponse {
  dossier: Dossier | null
}

// ============ OSS Pipeline Redesign Types ============

export type Stage4Status =
  | 'swe_agent_working'
  | 'swe_agent_done'
  | 'static_analysis_running'
  | 'static_analysis_done'
  | 'review_in_progress'
  | 'review_complete'
  | 'remediation_running'
  | 'remediation_done'
  | 'retrospective_complete'

export interface PipelineAssignment extends OSSAssignment {
  stage4Status: Stage4Status
  stage4PrNumber: number | null
  stage4PrBranch: string | null
  stage4ReviewRequested: boolean
  stage4SweDoneAt: string | null
  stage4SaRunId: string | null
  stage4SaConclusion: string | null
  stage4SaDoneAt: string | null
  stage4ReviewDoneAt: string | null
  stage4dSkipped: boolean | null
  stage4dPreCommitCount: number | null
  stage4dDoneAt: string | null
  language: string | null
  contextTier: number | null
  contextSources: string[] | null
  dossierCompleteness: Record<string, boolean> | null
}

export interface RetrospectiveEntry {
  repo: string
  issue_number: number
  created_at: string
  swe?: {
    pr_number?: number
    title?: string
    pr_branch?: string
    additions?: number
    deletions?: number
    changed_files?: number
    commit_count?: number
  }
  static_analysis?: {
    conclusion?: string
    run_id?: string
    jobs?: {
      name: string
      conclusion: string
      annotations?: {
        path: string
        line: number
        level: string
        message: string
      }[]
    }[]
    total_annotations?: number
  }
  review?: {
    inline_comment_count?: number
    actionable?: boolean
  }
  remediation?: {
    skipped?: boolean
    new_commits?: number
    additions?: number
    deletions?: number
    changed_files?: number
  }
  workflow?: {
    reproduced?: boolean
    verified?: boolean
    self_corrected?: boolean
    codeql?: boolean
    code_review?: boolean
    tool_installed?: boolean
    step_count?: number
    tools_used?: string[]
  }
  timing?: {
    assigned_at?: string
    swe_done_at?: string
    sa_done_at?: string
    review_done_at?: string
    remediation_done_at?: string
    completed_at?: string
  }
  data_quality?: {
    context_tier?: number
    dossier_completeness?: Record<string, boolean | number>
  }
  pipeline?: {
    language?: string
    swe_agent?: string
    review_agent?: string
    static_analysis?: string
    remediation_agent?: string
  }
}

export interface RepoHealthTarget extends OSSTarget {
  health?: OSSTarget['health'] & {
    prPatterns?: Record<string, unknown>
    detectedQuirks?: string[]
    analyzedAt?: string
  }
  dossier?: {
    sections?: DossierSections
    completeness?: Record<string, boolean | number>
    _meta?: Record<string, unknown>
  }
  _meta?: Record<string, unknown>
}

// ============ OSS Pipeline Redesign Response Types ============

export interface PipelineStatusResponse extends OSSBaseResponse {
  statuses: PipelineAssignment[]
}

export interface RetrospectiveLogsResponse extends OSSBaseResponse {
  logs: RetrospectiveEntry[]
}

export interface SignoffResponse extends OSSBaseResponse {
  pr_url?: string
  clean_branch?: string
  steps?: Record<string, unknown>
  conflict_warnings?: { number: number; title: string; mergeable: string }[]
  error?: string
}

// ============ Retrospective Batch Types ============

export interface PrCommit {
  sha: string
  date: string
  author: string
  message: string
}

export interface PrComment {
  author: string
  body: string
  created_at: string
  comment_type: 'regular' | 'inline'
  path?: string
  line?: number
}

export interface BatchSummary {
  batch_id: string
  created_at: string
  note?: string
  issue_count: number
  upstream_pr_count: number
  upstream_merged: number
  upstream_closed: number
  upstream_open: number
  has_fork_pr: number
}

export interface BatchAssignment {
  origin_slug: string
  issue_number: number
  assigned_at: string
  stage4_pr_number?: number
  context_tier?: number
  batch_id?: string
}

export interface BatchUpstreamPR {
  pr_url: string
  pr_number?: number
  title?: string
  state: string
  submitted_at?: string
  merged_at?: string
  closed_at?: string
  issue_number?: number
}

export interface UpstreamIssueMention {
  actor: string
  source_url: string
  source_title: string
  source_type: string
  created_at: string
}

export interface BatchRetroEntry extends RetrospectiveEntry {
  batch_id?: string
  context_issue_body?: string
  upstream_pr_body?: string
  raw_comments?: {
    fork_pr: PrComment[]
    upstream_pr: PrComment[]
  }
  upstream_issue_mentions?: UpstreamIssueMention[]
}

export interface BatchIssue {
  assignment: BatchAssignment
  upstream_pr?: BatchUpstreamPR
  retro: BatchRetroEntry
}

export interface BatchDetailResponse extends OSSBaseResponse {
  batch: BatchSummary
  issues: BatchIssue[]
  error?: string
}

export interface BatchListResponse extends OSSBaseResponse {
  batches: BatchSummary[]
}

// ============ Temporal (crimson-kitty) Types ============

export type TemporalState =
  | 'candidate'
  | 'eligible'
  | 'forked'
  | 'environment_ready'
  | 'reproduced'
  | 'fixed'
  | 'verified'
  | 'reviewed'
  | 'remediated'
  | 'submittable'
  | 'submitted'
  | 'merged'
  | 'closed_by_upstream'
  | 'aborted'
  | 'awaiting_human_review'

export type TemporalGateVerdict = 'pass' | 'fail' | 'defer'
export type TemporalSignalDecision = 'approve' | 'abort' | 'retry'

/** Structured override reason codes — Phase 0 / M0.2. Backend enforces
 *  that codes are scoped to their decision; `abort_other` requires a
 *  non-empty reason_text. */
export type TemporalApproveReasonCode = 'approve_clean' | 'approve_after_edit'
export type TemporalAbortReasonCode =
  | 'abort_scope_mismatch'
  | 'abort_quality'
  | 'abort_active_upstream'
  | 'abort_stale_issue'
  | 'abort_other'
export type TemporalRetryReasonCode = 'retry_transient' | 'retry_with_changes'
export type TemporalReasonCode =
  | TemporalApproveReasonCode
  | TemporalAbortReasonCode
  | TemporalRetryReasonCode

export interface TemporalEnvelope<T> {
  success: boolean
  data: T
  _meta?: Record<string, unknown>
  error?: string
}

export interface TemporalBatchSummary {
  batch_id: string
  issue_count: number
  /** Issues parked in the operator inbox. Added by the backend so the UI
   *  can split Active vs Archive tabs without fetching every batch. */
  deferred_count?: number
  /** True when deferred_count > 0 — the batch needs operator attention. */
  active?: boolean
}

export interface TemporalIssueSummary {
  batch_id: string
  issue_id: string
  current_state: string
  is_deferred: boolean
  /** Reason the run aborted — only set when current_state === 'aborted'.
   *  Explains stopped runs that have no failed gate (e.g. an activity
   *  crash like a fork 403, which never produces a gate verdict). */
  abort_reason?: string | null
  /** Abort classification. 'crashed' = an activity threw (retryable, no
   *  gate verdict exists); 'gate' = a gate failed the work; 'operator' =
   *  operator abort. Only 'crashed' is worth re-dispatching. */
  abort_kind?: 'crashed' | 'gate' | 'operator' | null
  deferred_at: string | null
  deferred_gate: string | null
  transition_count: number
  gate_count: number
}

export interface TemporalTransition {
  from: string
  to: string
  reason: string
  decided_by: string
  ts: string
}

export interface TemporalGateRecord {
  gate: string
  verdict: string
  reason: string
  evidence_data: Record<string, unknown> | null
  ts: string
}

export interface TemporalEventRecord {
  ts?: string
  type?: string
  [key: string]: unknown
}

export interface TemporalIssueDetail extends TemporalIssueSummary {
  transitions: TemporalTransition[]
  gates: TemporalGateRecord[]
  events: TemporalEventRecord[]
}

export interface TemporalBatchDetail {
  batch_id: string
  issue_count: number
  issues: TemporalIssueSummary[]
}

export interface TemporalInboxItem {
  batch_id: string
  issue_id: string
  // fields from inbox_entry.json (shape varies — keep flexible)
  state?: string
  gate?: string
  reason?: string
  score?: number | null
  queued_at?: string
  workflow_id?: string
  upstream_slug?: string
  issue_number?: number
  // Phase 5.4 enrichment — only populated when gate === 'operator_signoff'
  operator_pr_url?: string
  pr_title?: string
  pr_body_excerpt?: string
  [key: string]: unknown
}

export interface TemporalHealth {
  state_root: string
  state_root_exists: boolean
  batch_count: number
  cluster_check: string
}

export interface TemporalDispatchIssueInput {
  upstream_slug: string
  fork_slug?: string
  issue_number: number
  raw_brief?: string
  branch_name?: string
  base_branch?: string
}

export interface TemporalDispatchResult {
  batch_id: string
  workflow_id: string
  issue_count: number
}

export interface TemporalSignalResult {
  workflow_id: string
  decision: TemporalSignalDecision
  reason_code?: TemporalReasonCode | null
  reason_text?: string
  persisted?: Record<string, unknown> | null
}
