/**
 * Retrospective batches: the per-batch rollup built over a finished OSS run.
 */

import type { OSSBaseResponse, RetrospectiveEntry } from './oss'

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
