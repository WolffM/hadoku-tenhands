/**
 * API Endpoints for VibeDispatch
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
  WorkflowStatusResponse,
  OSSStage1Response,
  OSSStage2Response,
  OSSStage3Response,
  OSSStage4Response,
  OSSStage5Response,
  OSSStage5TrackingResponse,
  OSSForkAssignResponse,
  OSSSubmitResponse,
  OSSBaseResponse
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

/**
 * Get the status of the latest vibecheck workflow run
 */
export async function getWorkflowStatus(
  owner: string,
  repo: string
): Promise<WorkflowStatusResponse> {
  return apiClient.post<WorkflowStatusResponse>('/api/workflow-status', {
    owner,
    repo
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

// ============ Cache Management ============

/**
 * Clear the vibecheck status cache
 */
export async function clearCache(): Promise<ActionResponse> {
  return apiClient.post<ActionResponse>('/api/clear-cache')
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

// --- Stage 1: Target Repos (stubs) ---

export async function getOSSTargets(): Promise<OSSStage1Response> {
  return apiClient.get<OSSStage1Response>('/api/oss/stage1-targets')
}

export async function addOSSTarget(slug: string): Promise<OSSBaseResponse & { error?: string }> {
  return apiClient.post<OSSBaseResponse & { error?: string }>('/api/oss/add-target', { slug })
}

export async function removeOSSTarget(slug: string): Promise<OSSBaseResponse & { error?: string }> {
  return apiClient.post<OSSBaseResponse & { error?: string }>('/api/oss/remove-target', { slug })
}

// --- Stage 2: Scored Issues (stubs) ---

export async function getOSSScoredIssues(): Promise<OSSStage2Response> {
  return apiClient.get<OSSStage2Response>('/api/oss/stage2-issues')
}

// --- Stage 3: Fork & Assign ---

export async function getOSSAssigned(): Promise<OSSStage3Response> {
  return apiClient.get<OSSStage3Response>('/api/oss/stage3-assigned')
}

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

export async function getOSSForkPRs(): Promise<OSSStage4Response> {
  return apiClient.get<OSSStage4Response>('/api/oss/stage4-fork-prs')
}

export async function getOSSForkPRDetails(
  repo: string,
  prNumber: number
): Promise<PRDetailsResponse & { owner: string }> {
  return apiClient.post<PRDetailsResponse & { owner: string }>('/api/oss/fork-pr-details', {
    repo,
    pr_number: prNumber
  })
}

export async function approveOSSForkPR(
  repo: string,
  prNumber: number
): Promise<OSSBaseResponse & { message?: string; error?: string }> {
  return apiClient.post<OSSBaseResponse & { message?: string; error?: string }>(
    '/api/oss/approve-fork-pr',
    {
      repo,
      pr_number: prNumber
    }
  )
}

export async function mergeOSSForkPR(
  repo: string,
  prNumber: number,
  originSlug: string
): Promise<OSSBaseResponse & { message?: string; error?: string }> {
  return apiClient.post<OSSBaseResponse & { message?: string; error?: string }>(
    '/api/oss/merge-fork-pr',
    {
      repo,
      pr_number: prNumber,
      origin_slug: originSlug
    }
  )
}

// --- Stage 5: Submit Upstream ---

export async function getOSSReadyToSubmit(): Promise<OSSStage5Response> {
  return apiClient.get<OSSStage5Response>('/api/oss/stage5-submit')
}

export async function submitToOrigin(
  originSlug: string,
  repo: string,
  branch: string,
  title: string,
  body: string,
  baseBranch?: string
): Promise<OSSSubmitResponse> {
  return apiClient.post<OSSSubmitResponse>('/api/oss/submit-to-origin', {
    origin_slug: originSlug,
    repo,
    branch,
    title,
    body,
    base_branch: baseBranch || 'main'
  })
}

export async function getOSSSubmittedTracking(): Promise<OSSStage5TrackingResponse> {
  return apiClient.get<OSSStage5TrackingResponse>('/api/oss/stage5-tracking')
}
