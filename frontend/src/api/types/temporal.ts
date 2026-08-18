/**
 * Temporal (crimson-kitty) workflows: run state, gates, the operator inbox,
 * and the signals sent back to a waiting workflow.
 */

// ============ Temporal (crimson-kitty) Types ============

// Note on the wire format: `current_state` and `verdict` below are `string`,
// not closed unions, and deliberately so.
//
// There used to be a `TemporalState` union and a `TemporalGateVerdict` union
// here. Nothing consumed either — and `TemporalState` had drifted: the
// workflow emits `replicated` and `awaiting_signoff`, neither of which the
// union listed, while the union listed states (`eligible`, `environment_ready`,
// `reproduced`, `verified`, `merged`, …) the workflow never sets. Typing the
// field against it would have rejected real data.
//
// These values cross a Python/TypeScript boundary with no shared schema, so
// the frontend treats them as open strings and falls back on an unrecognised
// one (`GateResultRow`'s `|| 'secondary'`). Reintroduce a closed union only
// alongside something that keeps it honest against the backend.

export type TemporalSignalDecision = 'approve' | 'abort' | 'retry'

/** Structured override reason codes — Phase 0 / M0.2. Backend enforces
 *  that codes are scoped to their decision; `abort_other` requires a
 *  non-empty reason_text. */
type TemporalApproveReasonCode = 'approve_clean' | 'approve_after_edit'
type TemporalAbortReasonCode =
  | 'abort_scope_mismatch'
  | 'abort_quality'
  | 'abort_active_upstream'
  | 'abort_stale_issue'
  | 'abort_other'
type TemporalRetryReasonCode = 'retry_transient' | 'retry_with_changes'
export type TemporalReasonCode =
  TemporalApproveReasonCode | TemporalAbortReasonCode | TemporalRetryReasonCode

export interface TemporalBatchSummary {
  batch_id: string
  issue_count: number
  /** Issues parked in the operator inbox. Added by the backend so the UI
   *  can split Active vs Archive tabs without fetching every batch. */
  deferred_count?: number
  /** True when deferred_count > 0 — the batch needs operator attention. */
  active?: boolean
}

interface TemporalIssueSummary {
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

interface TemporalTransition {
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

interface TemporalEventRecord {
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

export interface TemporalSignalResult {
  workflow_id: string
  decision: TemporalSignalDecision
  reason_code?: TemporalReasonCode | null
  reason_text?: string
  persisted?: Record<string, unknown> | null
}
