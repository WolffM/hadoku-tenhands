/**
 * vibeCheck pipeline: the stage responses and the generic action envelope.
 */

import type { Issue, PRDetails, PullRequest, Stage1Repo, Stage2Repo, WorkflowRun } from './common'

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
