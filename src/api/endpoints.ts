/**
 * API Endpoints for VibeDispatch
 *
 * All API calls to the Flask backend.
 */

import { apiClient } from './client'
import type {
  ActionResponse,
  GlobalWorkflowRunsResponse,
  HealthCheckResponse,
  PRDetailsResponse,
  Stage1Response,
  Stage2Response,
  Stage3Response,
  Stage4Response,
  WorkflowStatusResponse
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
 * Run full pipeline (install + trigger) on a repo
 */
export async function runFullPipeline(
  owner: string,
  repo: string
): Promise<ActionResponse & { steps_completed?: string[] }> {
  return apiClient.post<ActionResponse & { steps_completed?: string[] }>('/api/run-full-pipeline', {
    owner,
    repo
  })
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

/**
 * Install vibecheck on multiple repos
 */
export async function batchInstallVibecheck(
  owner: string,
  repos: string[],
  onProgress?: (completed: number, total: number, result: BatchResult) => void
): Promise<BatchResult[]> {
  const results: BatchResult[] = []

  for (let i = 0; i < repos.length; i++) {
    const repo = repos[i]
    try {
      const response = await installVibecheck(owner, repo)
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
        error: err instanceof Error ? err.message : 'Unknown error'
      }
      results.push(result)
      onProgress?.(i + 1, repos.length, result)
    }
  }

  return results
}

/**
 * Run vibecheck on multiple repos
 */
export async function batchRunVibecheck(
  owner: string,
  repos: string[],
  onProgress?: (completed: number, total: number, result: BatchResult) => void
): Promise<BatchResult[]> {
  const results: BatchResult[] = []

  for (let i = 0; i < repos.length; i++) {
    const repo = repos[i]
    try {
      const response = await runVibecheck(owner, repo)
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
        error: err instanceof Error ? err.message : 'Unknown error'
      }
      results.push(result)
      onProgress?.(i + 1, repos.length, result)
    }
  }

  return results
}

/**
 * Assign Copilot to multiple issues
 */
export async function batchAssignCopilot(
  owner: string,
  issues: { repo: string; issueNumber: number }[],
  onProgress?: (
    completed: number,
    total: number,
    result: BatchResult & { issueNumber: number }
  ) => void
): Promise<(BatchResult & { issueNumber: number })[]> {
  const results: (BatchResult & { issueNumber: number })[] = []

  for (let i = 0; i < issues.length; i++) {
    const { repo, issueNumber } = issues[i]
    try {
      const response = await assignCopilot(owner, repo, issueNumber)
      const result = {
        repo,
        issueNumber,
        success: response.success,
        message: response.message,
        error: response.error
      }
      results.push(result)
      onProgress?.(i + 1, issues.length, result)
    } catch (err) {
      const result = {
        repo,
        issueNumber,
        success: false,
        error: err instanceof Error ? err.message : 'Unknown error'
      }
      results.push(result)
      onProgress?.(i + 1, issues.length, result)
    }
  }

  return results
}
