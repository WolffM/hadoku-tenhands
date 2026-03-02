/**
 * PipelineRunsPanel — Tab 3
 *
 * Shows pipeline assignments with progress bars, summary metrics,
 * report detail view (via backend-generated HTML in modal iframe), and signoff.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { signoffIssue, advancePipeline } from '../../api/endpoints'
import type { PipelineAssignment, Stage4Status } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'
import { Badge, getStage4BadgeVariant } from '../common/Badge'
import { SectionHeader } from '../common/SectionHeader'

/** Map stage4Status to progress bar segments (0-5 filled). */
const STAGE_PROGRESS: Record<Stage4Status, number> = {
  swe_agent_working: 1,
  swe_agent_done: 1,
  static_analysis_running: 2,
  static_analysis_done: 2,
  review_in_progress: 3,
  review_complete: 3,
  remediation_running: 4,
  remediation_done: 4,
  retrospective_complete: 5
}

const SEGMENT_LABELS = ['SWE', 'SA', 'Review', 'Remediation', 'Done']
const SEGMENT_CLASSES = ['seg--swe', 'seg--sa', 'seg--review', 'seg--remediation', 'seg--done']

function ProgressBar({ status }: { status: Stage4Status }) {
  const filled = STAGE_PROGRESS[status] ?? 0
  return (
    <div className="pipeline-progress" title={status}>
      {SEGMENT_LABELS.map((label, i) => (
        <div
          key={label}
          className={`pipeline-progress__seg ${SEGMENT_CLASSES[i]} ${i < filled ? 'pipeline-progress__seg--filled' : ''}`}
          title={label}
        />
      ))}
    </div>
  )
}

export function PipelineRunsPanel() {
  const ossPipelineRuns = usePipelineStore(state => state.ossPipelineRuns)
  const loadOSSPipelineRuns = usePipelineStore(state => state.loadOSSPipelineRuns)
  const loadOSSSubmittedPRs = usePipelineStore(state => state.loadOSSSubmittedPRs)
  const addLog = usePipelineStore(state => state.addLog)
  const excludedRepos = usePipelineStore(state => state.ossExcludedRepos)
  const [signingOff, setSigningOff] = useState<string | null>(null)
  const [advancing, setAdvancing] = useState<string | null>(null)
  const [reportUrl, setReportUrl] = useState<string | null>(null)

  const assignments = useMemo(
    () => ossPipelineRuns.items.filter(a => !excludedRepos.has(a.originSlug)),
    [ossPipelineRuns.items, excludedRepos]
  )

  // Summary metrics
  const metrics = useMemo(() => {
    const total = assignments.length
    const completed = assignments.filter(a => a.stage4Status === 'retrospective_complete').length
    const inProgress = total - completed
    return { total, completed, inProgress }
  }, [assignments])

  const handleSignoff = async (a: PipelineAssignment) => {
    const key = `${a.repo}-${a.stage4PrNumber}`
    if (!a.stage4PrNumber) {
      addLog('No fork PR number found for signoff', 'error')
      return
    }
    setSigningOff(key)
    addLog(`Signing off ${a.originSlug}#${a.issueNumber}...`, 'info')
    try {
      const result = await signoffIssue(a.repo, a.stage4PrNumber, a.originSlug)
      if (result.success) {
        addLog(`Signed off: ${result.pr_url || 'success'}`, 'success')
        void loadOSSPipelineRuns()
        void loadOSSSubmittedPRs()
      } else {
        addLog(`Signoff failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Signoff failed', 'error')
    } finally {
      setSigningOff(null)
    }
  }

  const handleAdvance = async (a: PipelineAssignment) => {
    const key = `${a.repo}-${a.forkIssueNumber}`
    setAdvancing(key)
    addLog(`Advancing pipeline for ${a.originSlug}#${a.issueNumber}...`, 'info')
    try {
      const result = await advancePipeline(a.repo, a.forkIssueNumber)
      if (result.success) {
        addLog('Pipeline advanced', 'success')
        void loadOSSPipelineRuns()
      } else {
        addLog(`Advance failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Advance failed', 'error')
    } finally {
      setAdvancing(null)
    }
  }

  const handleOpenReport = (a: PipelineAssignment) => {
    // Build URL for the backend-generated HTML report
    const baseUrl = window.location.origin
    const url = `${baseUrl}/dispatch/api/oss/issue-report/${a.repo}/${a.issueNumber}`
    setReportUrl(url)
  }

  if (ossPipelineRuns.loading && ossPipelineRuns.items.length === 0) {
    return <LoadingState text="Loading pipeline runs..." />
  }

  if (ossPipelineRuns.items.length === 0) {
    return (
      <div className="stage-panel">
        <EmptyState
          icon="\u{2699}\u{FE0F}"
          title="No pipeline runs"
          description="Assign issues in the Fork & Assign tab to start the pipeline."
        />
      </div>
    )
  }

  return (
    <div className="stage-panel">
      {/* Summary Metrics */}
      <div className="metric-row">
        <div className="metric-card">
          <div className="metric-card__label">Total</div>
          <div className="metric-card__value">{metrics.total}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card__label">In Progress</div>
          <div className="metric-card__value">{metrics.inProgress}</div>
        </div>
        <div className="metric-card">
          <div className="metric-card__label">Completed</div>
          <div className="metric-card__value">{metrics.completed}</div>
        </div>
      </div>

      {/* Assignments Table */}
      <div className="stage-section">
        <SectionHeader
          icon={'\u{2699}\u{FE0F}'}
          title="Pipeline Assignments"
          count={assignments.length}
        />

        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th>Origin Repo</th>
                <th>#</th>
                <th>Progress</th>
                <th>Status</th>
                <th>Assigned</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((a: PipelineAssignment) => {
                const signoffKey = `${a.repo}-${a.stage4PrNumber}`
                const advanceKey = `${a.repo}-${a.forkIssueNumber}`
                const isComplete = a.stage4Status === 'retrospective_complete'

                return (
                  <tr key={`${a.originSlug}-${a.issueNumber}`}>
                    <td>
                      <span className="repo-link">{a.originSlug}</span>
                    </td>
                    <td className="text-light">#{a.issueNumber}</td>
                    <td>
                      <ProgressBar status={a.stage4Status} />
                    </td>
                    <td>
                      <Badge variant={getStage4BadgeVariant(a.stage4Status || 'swe_agent_working')}>
                        {(a.stage4Status || 'swe_agent_working').replace(/_/g, ' ')}
                      </Badge>
                    </td>
                    <td className="text-light">{formatTimeAgo(a.assignedAt)}</td>
                    <td>
                      <div className="action-buttons">
                        <button
                          className="btn btn--secondary btn--sm"
                          onClick={() => handleOpenReport(a)}
                        >
                          Report
                        </button>
                        {!isComplete && (
                          <button
                            className="btn btn--secondary btn--sm"
                            onClick={() => {
                              void handleAdvance(a)
                            }}
                            disabled={advancing === advanceKey}
                          >
                            {advancing === advanceKey ? '...' : 'Advance'}
                          </button>
                        )}
                        {isComplete && a.stage4PrNumber && (
                          <button
                            className="btn btn--primary btn--sm"
                            onClick={() => {
                              void handleSignoff(a)
                            }}
                            disabled={signingOff === signoffKey}
                          >
                            {signingOff === signoffKey ? 'Signing off...' : 'Signoff'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Report Modal */}
      {reportUrl && (
        <div className="report-modal" onClick={() => setReportUrl(null)}>
          <div className="report-modal__content" onClick={e => e.stopPropagation()}>
            <div className="report-modal__header">
              <h3>Pipeline Report</h3>
              <button className="btn btn--secondary btn--sm" onClick={() => setReportUrl(null)}>
                Close
              </button>
            </div>
            <iframe className="report-modal__iframe" src={reportUrl} title="Pipeline Report" />
          </div>
        </div>
      )}
    </div>
  )
}
