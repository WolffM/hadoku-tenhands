/**
 * PipelineRunsPanel — Tab 3
 *
 * Shows pipeline assignments with progress bars, summary metrics,
 * report detail view (via backend-generated HTML in modal iframe), and signoff.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { useAsyncAction } from '../../hooks'
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

function StagePipelineBar({ status }: { status: Stage4Status }) {
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
  const [reportUrl, setReportUrl] = useState<string | null>(null)
  // Demo-only: the report HTML rendered inline via srcdoc (see handleOpenReport).
  const [reportDoc, setReportDoc] = useState<string | null>(null)

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

  const [signingOff, runSignoff] = useAsyncAction({
    startMsg: key => `Signing off ${key}…`,
    successMsg: result => `Signed off: ${(result.pr_url as string) || 'success'}`,
    failMsg: 'Signoff failed',
    onSuccess: () => {
      void loadOSSPipelineRuns()
      void loadOSSSubmittedPRs()
    }
  })

  const [advancing, runAdvance] = useAsyncAction({
    startMsg: key => `Advancing pipeline for ${key}…`,
    successMsg: 'Pipeline advanced',
    failMsg: 'Advance failed',
    onSuccess: () => loadOSSPipelineRuns()
  })

  const handleSignoff = (a: PipelineAssignment, key: string) => {
    if (!a.stage4PrNumber) {
      addLog('No fork PR number found for signoff', 'error')
      return
    }
    return runSignoff(key, () => signoffIssue(a.repo, a.stage4PrNumber!, a.originSlug))
  }

  const handleAdvance = (a: PipelineAssignment) =>
    runAdvance(`${a.originSlug}#${a.issueNumber}`, () => advancePipeline(a.repo, a.forkIssueNumber))

  const handleOpenReport = (a: PipelineAssignment) => {
    // Build URL for the backend-generated HTML report
    const baseUrl = window.location.origin
    const url = `${baseUrl}/tenhands/api/oss/issue-report/${a.repo}/${a.issueNumber}`
    const isDemo = (window as unknown as { __TENHANDS_DEMO__?: boolean }).__TENHANDS_DEMO__
    if (isDemo) {
      // The demo has no backend, and an iframe `src` navigation doesn't route
      // through the demo's fetch stub — so fetch the report HTML (the stub
      // answers it) and render it inline via srcdoc. Prod keeps the `src` path.
      void fetch(url)
        .then(r => r.text())
        .then(html => setReportDoc(html))
        .catch(() => setReportDoc('<p style="font:14px sans-serif;padding:1rem">Report unavailable in the demo.</p>'))
      return
    }
    setReportUrl(url)
  }

  if (ossPipelineRuns.loading && ossPipelineRuns.items.length === 0) {
    return <LoadingState text="Loading pipeline runs…" />
  }

  if (ossPipelineRuns.items.length === 0) {
    return (
      <div className="stage-panel">
        <EmptyState
          icon="⚙️"
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
          icon={'⚙️'}
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
              {assignments.map((a: PipelineAssignment, idx: number) => {
                const signoffKey = `${a.repo}-${a.stage4PrNumber}`
                const advanceKey = `${a.repo}-${a.forkIssueNumber}`
                const isComplete = a.stage4Status === 'retrospective_complete'

                return (
                  <tr
                    key={`${a.originSlug}-${a.issueNumber}-${a.assignedAt ?? a.forkIssueNumber ?? idx}`}
                  >
                    <td>
                      <span className="repo-link">{a.originSlug}</span>
                    </td>
                    <td className="text-light">#{a.issueNumber}</td>
                    <td>
                      <StagePipelineBar status={a.stage4Status} />
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
                            {advancing === advanceKey ? '…' : 'Advance'}
                          </button>
                        )}
                        {isComplete && a.stage4PrNumber && (
                          <button
                            className="btn btn--primary btn--sm"
                            onClick={() => {
                              void handleSignoff(a, signoffKey)
                            }}
                            disabled={signingOff === signoffKey}
                          >
                            {signingOff === signoffKey ? 'Signing off…' : 'Signoff'}
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
      {(reportUrl || reportDoc) && (
        <div className="report-modal" onClick={() => { setReportUrl(null); setReportDoc(null) }}>
          <div className="report-modal__content" onClick={e => e.stopPropagation()}>
            <div className="report-modal__header">
              <h3>Pipeline Report</h3>
              <button
                className="btn btn--secondary btn--sm"
                onClick={() => { setReportUrl(null); setReportDoc(null) }}
              >
                Close
              </button>
            </div>
            <iframe
              className="report-modal__iframe"
              // Prod loads the backend URL directly; the demo renders the
              // fixture HTML inline. The report is our own generated HTML that
              // builds itself from embedded data via a script, so it needs
              // `allow-scripts` to render at all — WITHOUT `allow-same-origin`,
              // so it stays a null-origin sandbox that can't reach the parent,
              // its cookies, or same-origin resources.
              {...(reportDoc ? { srcDoc: reportDoc } : { src: reportUrl ?? undefined })}
              title="Pipeline Report"
              sandbox="allow-scripts"
            />
          </div>
        </div>
      )}
    </div>
  )
}
