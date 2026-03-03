/**
 * ProductionReviewPanel — Tab 4
 *
 * Production PR command center showing all submitted upstream PRs with
 * comments, labels, merge/close status, review decisions, and refresh polling.
 */

import { useMemo } from 'react'
import { usePipelineStore } from '../../store'
import type { SubmittedPR } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'
import { Badge, getSubmittedPRBadge } from '../common/Badge'
import { SectionHeader } from '../common/SectionHeader'

export function ProductionReviewPanel() {
  const ossSubmittedPRs = usePipelineStore(state => state.ossSubmittedPRs)
  const loadOSSSubmittedPRs = usePipelineStore(state => state.loadOSSSubmittedPRs)
  const addLog = usePipelineStore(state => state.addLog)
  const excludedRepos = usePipelineStore(state => state.ossExcludedRepos)

  const allSubmitted = ossSubmittedPRs.items as (SubmittedPR & {
    comment_count?: number
    labels?: string[]
  })[]

  const submitted = useMemo(
    () => allSubmitted.filter(pr => !excludedRepos.has(pr.originSlug)),
    [allSubmitted, excludedRepos]
  )

  // Summary counts
  const counts = useMemo(() => {
    const total = submitted.length
    const open = submitted.filter(pr => pr.state === 'open').length
    const merged = submitted.filter(pr => pr.state === 'merged').length
    const closed = submitted.filter(pr => pr.state === 'closed').length
    return { total, open, merged, closed }
  }, [submitted])

  const handleRefresh = async () => {
    addLog('Polling upstream PR statuses...', 'info')
    try {
      await loadOSSSubmittedPRs()
      addLog(`Status updated for ${submitted.length} PR(s)`, 'success')
    } catch {
      addLog('Failed to refresh PR statuses', 'error')
    }
  }

  if (ossSubmittedPRs.loading && allSubmitted.length === 0) {
    return <LoadingState text="Polling upstream PR statuses..." />
  }

  if (allSubmitted.length === 0) {
    return (
      <div className="stage-panel">
        <EmptyState
          icon="\u{1F4E4}"
          title="No submitted PRs"
          description="Sign off on completed pipeline runs to create upstream PRs."
        />
      </div>
    )
  }

  return (
    <div className="stage-panel">
      {/* Summary Bar */}
      <div className="metric-row">
        <div className="metric-card">
          <div className="metric-card__label">Total</div>
          <div className="metric-card__value">{counts.total}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card__label">Open</div>
          <div className="metric-card__value">{counts.open}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card__label">Merged</div>
          <div className="metric-card__value">{counts.merged}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card__label">Closed</div>
          <div className="metric-card__value">{counts.closed}</div>
        </div>
      </div>

      {/* Submitted PRs Table */}
      <div className="stage-section">
        <SectionHeader icon={'\u{1F4CA}'} title="Upstream PRs" count={submitted.length}>
          <button
            className="btn btn--secondary btn--sm"
            onClick={() => {
              void handleRefresh()
            }}
            disabled={ossSubmittedPRs.loading}
          >
            {ossSubmittedPRs.loading ? 'Refreshing...' : 'Refresh Status'}
          </button>
        </SectionHeader>

        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Origin Repo</th>
                <th>PR</th>
                <th>Title</th>
                <th>Status</th>
                <th>Comments</th>
                <th>Labels</th>
                <th>Submitted</th>
                <th>Last Polled</th>
              </tr>
            </thead>
            <tbody>
              {submitted.map((pr, idx) => (
                <tr key={pr.prUrl || idx}>
                  <td>
                    <span className="repo-link">{pr.originSlug}</span>
                  </td>
                  <td>
                    {pr.prUrl ? (
                      <a
                        href={pr.prUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="issue-link"
                      >
                        #{pr.prNumber || '?'}
                      </a>
                    ) : (
                      <span className="text-light">
                        {pr.prNumber ? `#${pr.prNumber}` : '\u2014'}
                      </span>
                    )}
                  </td>
                  <td>{pr.title}</td>
                  <td>
                    {(() => {
                      const b = getSubmittedPRBadge(pr)
                      return <Badge variant={b.variant}>{b.label}</Badge>
                    })()}
                  </td>
                  <td className="text-light">{pr.comment_count ?? 0}</td>
                  <td className="text-light">
                    {(pr.labels ?? []).length > 0 ? (pr.labels ?? []).join(', ') : '\u2014'}
                  </td>
                  <td className="text-light">{formatTimeAgo(pr.submittedAt)}</td>
                  <td className="text-light">
                    {pr.lastPolledAt ? formatTimeAgo(pr.lastPolledAt) : '\u2014'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
