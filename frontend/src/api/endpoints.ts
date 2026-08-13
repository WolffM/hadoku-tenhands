/**
 * API Endpoints for TenHands
 *
 * All API calls to the Flask backend.
 */

import { apiClient } from './client'
import { getErrorMessage } from '../utils'
import type {
  ActionResponse,
  GlobalWorkflowRunsResponse,
  HealthCheckResponse,
  PRDetailsResponse,
  Stage1Response,
  Stage2Response,
  Stage3Response,
  Stage4Response,
  OSSStage1Response,
  OSSStage2Response,
  OSSStage5TrackingResponse,
  OSSForkAssignResponse,
  OSSBaseResponse,
  OSSDossierResponse,
  PipelineStatusResponse,
  RetrospectiveLogsResponse,
  SignoffResponse,
  BatchListResponse,
  BatchDetailResponse,
  PrCommit,
  TemporalBatchSummary,
  TemporalBatchDetail,
  TemporalIssueDetail,
  TemporalInboxItem,
  TemporalSignalDecision,
  TemporalReasonCode,
  TemporalSignalResult,
  TaskAutoStatus,
  TaskAutoTaskDetail
} from './types'

// ============ Stage APIs ============

/**
 * Get repos that need vibecheck installed (Stage 1)
 */
export async function getStage1Repos(): Promise<Stage1Response> {
  return apiClient.get<Stage1Response>('/api/stage1-repos')
}

/**
 * Get repos with vibecheck installed and run info (Stage 2)
 */
export async function getStage2Repos(): Promise<Stage2Response> {
  return apiClient.get<Stage2Response>('/api/stage2-repos')
}

/**
 * Get vibecheck issues for Copilot assignment (Stage 3)
 */
export async function getStage3Issues(): Promise<Stage3Response> {
  return apiClient.get<Stage3Response>('/api/stage3-issues')
}

/**
 * Get open PRs for review (Stage 4)
 */
export async function getStage4PRs(): Promise<Stage4Response> {
  return apiClient.get<Stage4Response>('/api/stage4-prs')
}

// ============ Action APIs ============

/**
 * Install vibecheck workflow on a repo
 */
export async function installVibecheck(owner: string, repo: string): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/install-vibecheck', {
    owner,
    repo
  })
}

/**
 * Trigger vibecheck workflow on a repo
 */
export async function runVibecheck(owner: string, repo: string): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/run-vibecheck', { owner, repo })
}

/**
 * Assign Copilot to an issue
 */
export async function assignCopilot(
  owner: string,
  repo: string,
  issueNumber: number
): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/assign-copilot', {
    owner,
    repo,
    issue_number: issueNumber
  })
}

/**
 * Approve a pull request
 */
export async function approvePR(
  owner: string,
  repo: string,
  prNumber: number
): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/approve-pr', {
    owner,
    repo,
    pr_number: prNumber
  })
}

/**
 * Mark a draft PR as ready for review
 */
export async function markPRReady(
  owner: string,
  repo: string,
  prNumber: number
): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/mark-pr-ready', {
    owner,
    repo,
    pr_number: prNumber
  })
}

/**
 * Merge a pull request
 */
export async function mergePR(
  owner: string,
  repo: string,
  prNumber: number
): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/merge-pr', {
    owner,
    repo,
    pr_number: prNumber
  })
}

// ============ Detail APIs ============

/**
 * Get detailed info about a PR including diff
 */
export async function getPRDetails(
  owner: string,
  repo: string,
  prNumber: number
): Promise<PRDetailsResponse> {
  return apiClient.post<PRDetailsResponse>('/api/pr-details', {
    owner,
    repo,
    pr_number: prNumber
  })
}

// ============ Health & Monitoring ============

/**
 * Get the authenticated GitHub owner
 */
export async function getOwner(): Promise<{ success: boolean; owner: string }> {
  return apiClient.get<{ success: boolean; owner: string }>('/api/owner')
}

/**
 * Get API health status
 */
export async function getHealthCheck(): Promise<HealthCheckResponse> {
  return apiClient.get<HealthCheckResponse>('/api/healthcheck')
}

/**
 * Get recent workflow runs across all repos
 */
export async function getGlobalWorkflowRuns(): Promise<GlobalWorkflowRunsResponse> {
  return apiClient.get<GlobalWorkflowRunsResponse>('/api/global-workflow-runs')
}

// ============ Batch Operations ============

export interface BatchResult {
  repo: string
  success: boolean
  message?: string
  error?: string
}

// ============ Workflow Update APIs ============

/**
 * Update vibecheck workflow on a repo to latest version
 */
export async function updateVibecheck(
  owner: string,
  repo: string,
  template?: string
): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/update-vibecheck', {
    owner,
    repo,
    template
  })
}

/**
 * Update vibecheck on multiple repos
 */
export async function batchUpdateVibecheck(
  owner: string,
  repos: string[],
  onProgress?: (completed: number, total: number, result: BatchResult) => void
): Promise<BatchResult[]> {
  const results: BatchResult[] = []

  for (let i = 0; i < repos.length; i++) {
    const repo = repos[i]
    try {
      const response = await updateVibecheck(owner, repo)
      const result: BatchResult = {
        repo,
        success: response.success,
        message: response.message,
        error: response.error
      }
      results.push(result)
      onProgress?.(i + 1, repos.length, result)
    } catch (err) {
      const result: BatchResult = {
        repo,
        success: false,
        error: getErrorMessage(err)
      }
      results.push(result)
      onProgress?.(i + 1, repos.length, result)
    }
  }

  return results
}

// ============ OSS Pipeline APIs ============

// --- Stage 1: Target Repos ---

export async function getOSSTargets(): Promise<OSSStage1Response> {
  return apiClient.get<OSSStage1Response>('/api/oss/stage1-targets')
}

// --- Stage 2: Scored Issues ---

export async function getOSSScoredIssues(): Promise<OSSStage2Response> {
  return apiClient.get<OSSStage2Response>('/api/oss/stage2-issues')
}

export async function getOSSDossier(slug: string): Promise<OSSDossierResponse> {
  return apiClient.get<OSSDossierResponse>(`/api/oss/dossier/${slug}`)
}

export async function refreshOSSTarget(
  slug: string
): Promise<OSSBaseResponse & { message?: string }> {
  return apiClient.post<OSSBaseResponse & { message?: string }>('/api/oss/refresh-target', {
    slug
  })
}

// --- Stage 3: Fork & Assign ---

export async function selectOSSIssue(
  originOwner: string,
  repo: string,
  issueNumber: number,
  issueTitle: string,
  issueUrl: string
): Promise<OSSBaseResponse & { already_selected?: boolean }> {
  return apiClient.post<OSSBaseResponse & { already_selected?: boolean }>('/api/oss/select-issue', {
    origin_owner: originOwner,
    repo,
    issue_number: issueNumber,
    issue_title: issueTitle,
    issue_url: issueUrl
  })
}

export async function forkAndAssign(
  originOwner: string,
  repo: string,
  issueNumber: number,
  issueTitle: string,
  issueUrl: string
): Promise<OSSForkAssignResponse> {
  return apiClient.post<OSSForkAssignResponse>('/api/oss/fork-and-assign', {
    origin_owner: originOwner,
    repo,
    issue_number: issueNumber,
    issue_title: issueTitle,
    issue_url: issueUrl
  })
}

// --- Stage 4: Review on Fork ---

// --- Stage 5: Submit Upstream ---

export async function pollSubmittedPRs(): Promise<OSSStage5TrackingResponse> {
  return apiClient.post<OSSStage5TrackingResponse>('/api/oss/poll-submitted-prs', {})
}

// --- Pipeline Runs (Redesigned Tab 3) ---

export async function getPipelineStatus(): Promise<PipelineStatusResponse> {
  return apiClient.get<PipelineStatusResponse>('/api/oss/pipeline-status')
}

export async function getRetrospectiveLogs(): Promise<RetrospectiveLogsResponse> {
  return apiClient.get<RetrospectiveLogsResponse>('/api/oss/retrospective-logs')
}

export async function advancePipeline(
  repo: string,
  forkIssueNumber: number
): Promise<OSSBaseResponse & { error?: string }> {
  return apiClient.post<OSSBaseResponse & { error?: string }>('/api/oss/advance-pipeline', {
    repo,
    fork_issue_number: forkIssueNumber
  })
}

export async function signoffIssue(
  repo: string,
  prNumber: number,
  originSlug: string
): Promise<SignoffResponse> {
  return apiClient.post<SignoffResponse>('/api/oss/signoff', {
    repo,
    pr_number: prNumber,
    origin_slug: originSlug
  })
}

// --- Retrospective Batches ---

export async function getRetroBatches(): Promise<BatchListResponse> {
  return apiClient.get<BatchListResponse>('/api/oss/retro/batches')
}

export async function getRetroBatchDetail(batchId: string): Promise<BatchDetailResponse> {
  return apiClient.get<BatchDetailResponse>(`/api/oss/retro/batch/${batchId}`)
}

export async function getRetroPRCommits(
  originSlug: string,
  prNumber: number,
  submittedAfter?: string
): Promise<{ success: boolean; commits: PrCommit[] }> {
  const params = submittedAfter ? `?submitted_after=${encodeURIComponent(submittedAfter)}` : ''
  return apiClient.get(`/api/oss/retro/pr-commits/${originSlug}/${prNumber}${params}`)
}

// --- Repo Health (Redesigned Tab 1) ---

export async function computeOSSTarget(
  slug: string
): Promise<OSSBaseResponse & { message?: string }> {
  return apiClient.post<OSSBaseResponse & { message?: string }>('/api/oss/compute-target', {
    slug
  })
}

// ============ Temporal (crimson-kitty) APIs ============

/**
 * These endpoints used to return `{success, data, _meta}` and be unwrapped with
 * a `.data` deref that existed for this module and nothing else. The backend now
 * returns the flat `{success, ...payload}` every other tenhands route returns —
 * see the docstring on `_envelope` in backend/routes/temporal_routes.py for why
 * the nested shape was there and why it was the odd one out.
 *
 * What survives the flattening is the THROW. Every temporal store action is a
 * bare `try { await getTemporalX() } catch (err) { ...getErrorMessage(err) }`,
 * so a `success: false` has to raise to become a visible error. Returning the
 * body and letting the caller check `.success` — the pattern ossStore and
 * vibeCheckStore use — would turn a failed load into an empty panel with no
 * message, which is the failure mode worth the most care here.
 */
interface FlatBody {
  success: boolean
  error?: string
}

function assertOk<T extends FlatBody>(body: T): T {
  if (!body.success) {
    throw new Error(body.error ?? 'temporal request failed')
  }
  return body
}

export async function getTemporalBatches(): Promise<TemporalBatchSummary[]> {
  const body = assertOk(
    await apiClient.get<{ batches: TemporalBatchSummary[] } & FlatBody>('/api/temporal/batches')
  )
  return body.batches
}

export async function getTemporalBatch(batchId: string): Promise<TemporalBatchDetail> {
  return assertOk(
    await apiClient.get<TemporalBatchDetail & FlatBody>(
      `/api/temporal/batch/${encodeURIComponent(batchId)}`
    )
  )
}

export async function getTemporalIssue(
  batchId: string,
  issueId: string
): Promise<TemporalIssueDetail> {
  return assertOk(
    await apiClient.get<TemporalIssueDetail & FlatBody>(
      `/api/temporal/issue/${encodeURIComponent(batchId)}/${encodeURIComponent(issueId)}`
    )
  )
}

export async function getTemporalEvidenceList(
  batchId: string,
  issueId: string
): Promise<{ stages: Record<string, string[]> }> {
  return assertOk(
    await apiClient.get<{ stages: Record<string, string[]> } & FlatBody>(
      `/api/temporal/evidence/${encodeURIComponent(batchId)}/${encodeURIComponent(issueId)}`
    )
  )
}

export async function getTemporalEvidenceFile(
  batchId: string,
  issueId: string,
  filepath: string
): Promise<{ path: string; content: string }> {
  return assertOk(
    await apiClient.get<{ path: string; content: string } & FlatBody>(
      `/api/temporal/evidence/${encodeURIComponent(batchId)}/${encodeURIComponent(issueId)}/${filepath}`
    )
  )
}

export async function getTemporalInbox(): Promise<{
  items: TemporalInboxItem[]
  count: number
}> {
  return assertOk(
    await apiClient.get<{ items: TemporalInboxItem[]; count: number } & FlatBody>(
      '/api/temporal/inbox'
    )
  )
}

export async function sendTemporalSignal(
  workflowId: string,
  decision: TemporalSignalDecision,
  options?: {
    reasonCode?: TemporalReasonCode | null
    reasonText?: string
  }
): Promise<TemporalSignalResult> {
  return assertOk(
    await apiClient.post<TemporalSignalResult & FlatBody>(
      `/api/temporal/issue/${encodeURIComponent(workflowId)}/signal`,
      {
        decision,
        reason_code: options?.reasonCode ?? null,
        reason_text: options?.reasonText ?? ''
      }
    )
  )
}

// ============ Task Automation ============

/** Every automation board, its tasks by lane, and its open taskauto PRs. */
export async function getTaskAutoStatus(): Promise<TaskAutoStatus> {
  return apiClient.get<TaskAutoStatus>('/api/taskauto/status')
}

/** One task end to end: its plan, every claim taken on it, and its PR. */
export async function getTaskAutoTask(board: string, taskId: string): Promise<TaskAutoTaskDetail> {
  return apiClient.get<TaskAutoTaskDetail>(
    `/api/taskauto/task/${encodeURIComponent(board)}/${encodeURIComponent(taskId)}`
  )
}

/** Merge one taskauto PR. Deliberately one at a time — this is the human gate. */
export async function mergeTaskAutoPR(
  repo: string,
  number: number,
  auto = false
): Promise<{ success: boolean; error?: string; scheduled?: boolean }> {
  return apiClient.post('/api/taskauto/merge', { repo, number, auto })
}
