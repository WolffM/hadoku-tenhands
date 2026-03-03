/**
 * Normalize API responses that may arrive in snake_case or camelCase.
 *
 * The backend _normalize_assignment() converts to camelCase, but if a stale
 * backend is running without that converter, the frontend receives snake_case.
 * This utility ensures the frontend always works regardless.
 */

import type { PipelineAssignment, Stage4Status, SubmittedPR } from '../api/types'

/** Pick the first defined value from candidates. */
function pick<T>(record: Record<string, unknown>, ...keys: string[]): T | undefined {
  for (const k of keys) {
    if (record[k] !== undefined && record[k] !== null) return record[k] as T
  }
  return undefined
}

/**
 * Normalize a raw pipeline assignment object (snake_case or camelCase) into
 * the PipelineAssignment interface the frontend expects.
 */
export function normalizePipelineAssignment(raw: Record<string, unknown>): PipelineAssignment {
  return {
    originSlug: pick<string>(raw, 'originSlug', 'origin_slug') ?? '',
    repo: pick<string>(raw, 'repo') ?? '',
    issueNumber: pick<number>(raw, 'issueNumber', 'issue_number') ?? 0,
    forkIssueNumber: pick<number>(raw, 'forkIssueNumber', 'fork_issue_number') ?? 0,
    forkIssueUrl: pick<string>(raw, 'forkIssueUrl', 'fork_issue_url') ?? '',
    assignedAt: pick<string>(raw, 'assignedAt', 'assigned_at') ?? '',
    stage4Status: pick<Stage4Status>(raw, 'stage4Status', 'stage4_status') ?? 'swe_agent_working',
    stage4PrNumber: pick<number>(raw, 'stage4PrNumber', 'stage4_pr_number') ?? null,
    stage4PrBranch: pick<string>(raw, 'stage4PrBranch', 'stage4_pr_branch') ?? null,
    stage4ReviewRequested:
      pick<boolean>(raw, 'stage4ReviewRequested', 'stage4_review_requested') ?? false,
    stage4SweDoneAt: pick<string>(raw, 'stage4SweDoneAt', 'stage4_swe_done_at') ?? null,
    stage4SaRunId: pick<string>(raw, 'stage4SaRunId', 'stage4_sa_run_id') ?? null,
    stage4SaConclusion: pick<string>(raw, 'stage4SaConclusion', 'stage4_sa_conclusion') ?? null,
    stage4SaDoneAt: pick<string>(raw, 'stage4SaDoneAt', 'stage4_sa_done_at') ?? null,
    stage4ReviewDoneAt: pick<string>(raw, 'stage4ReviewDoneAt', 'stage4_review_done_at') ?? null,
    stage4dSkipped: pick<boolean>(raw, 'stage4dSkipped', 'stage4d_skipped') ?? null,
    stage4dPreCommitCount:
      pick<number>(raw, 'stage4dPreCommitCount', 'stage4d_pre_commit_count') ?? null,
    stage4dDoneAt: pick<string>(raw, 'stage4dDoneAt', 'stage4d_done_at') ?? null,
    language: pick<string>(raw, 'language') ?? null,
    contextTier: pick<number>(raw, 'contextTier', 'context_tier') ?? null,
    contextSources: pick<string[]>(raw, 'contextSources', 'context_sources') ?? null,
    dossierCompleteness:
      pick<Record<string, boolean>>(raw, 'dossierCompleteness', 'dossier_completeness') ?? null
  }
}

/**
 * Normalize a raw submitted PR object (snake_case or camelCase) into
 * the SubmittedPR interface the frontend expects.
 */
export function normalizeSubmittedPR(
  raw: Record<string, unknown>
): SubmittedPR & { comment_count?: number; labels?: string[] } {
  return {
    originSlug: pick<string>(raw, 'originSlug', 'origin_slug') ?? '',
    prUrl: pick<string>(raw, 'prUrl', 'pr_url') ?? '',
    prNumber: pick<number>(raw, 'prNumber', 'pr_number'),
    title: pick<string>(raw, 'title') ?? '',
    state: pick<string>(raw, 'state') ?? 'open',
    reviewDecision: pick<string>(raw, 'reviewDecision', 'review_decision'),
    mergedAt: pick<string>(raw, 'mergedAt', 'merged_at'),
    closedAt: pick<string>(raw, 'closedAt', 'closed_at'),
    lastPolledAt: pick<string>(raw, 'lastPolledAt', 'last_polled_at'),
    submittedAt: pick<string>(raw, 'submittedAt', 'submitted_at') ?? '',
    comment_count: pick<number>(raw, 'comment_count', 'commentCount'),
    labels: pick<string[]>(raw, 'labels')
  }
}
