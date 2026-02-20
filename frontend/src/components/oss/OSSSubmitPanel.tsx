/**
 * OSSSubmitPanel — Stage 5
 *
 * Submit PRs from fork to upstream origin repos.
 * Shows items ready to submit + tracking of already-submitted PRs.
 */

import { useState, useEffect } from 'react'
import { usePipelineStore } from '../../store'
import { submitToOrigin, getOSSSubmittedTracking } from '../../api/endpoints'
import type { ReadyToSubmit, SubmittedPR } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'

export function OSSSubmitPanel() {
  const ossStage5 = usePipelineStore(state => state.ossStage5)
  const removeOSSReadyToSubmit = usePipelineStore(state => state.removeOSSReadyToSubmit)
  const addLog = usePipelineStore(state => state.addLog)

  const [submittedPRs, setSubmittedPRs] = useState<SubmittedPR[]>([])
  const [trackingLoading, setTrackingLoading] = useState(false)
  const [submitting, setSubmitting] = useState<string | null>(null)

  // Inline editor state
  const [editingItem, setEditingItem] = useState<ReadyToSubmit | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editBody, setEditBody] = useState('')

  // Load submitted PRs on mount
  useEffect(() => {
    const loadTracking = async () => {
      setTrackingLoading(true)
      try {
        const result = await getOSSSubmittedTracking()
        if (result.success) {
          setSubmittedPRs(result.submitted)
        }
      } catch {
        // Silent failure for tracking
      } finally {
        setTrackingLoading(false)
      }
    }
    void loadTracking()
  }, [])

  const readyItems = ossStage5.items

  const startEditing = (item: ReadyToSubmit) => {
    setEditingItem(item)
    setEditTitle(item.title)
    setEditBody(
      `## Summary\n\nFixes ${item.originSlug}#: ${item.title}\n\n## Changes\n\nThis PR addresses the issue described above.`
    )
  }

  const cancelEditing = () => {
    setEditingItem(null)
    setEditTitle('')
    setEditBody('')
  }

  const handleSubmit = async (item: ReadyToSubmit) => {
    const key = `${item.originSlug}-${item.branch}`
    setSubmitting(key)
    addLog(`Submitting PR to ${item.originSlug}...`, 'info')

    try {
      const result = await submitToOrigin(
        item.originSlug,
        item.repo,
        item.branch,
        editTitle || item.title,
        editBody,
        item.baseBranch
      )

      if (result.success) {
        addLog(`PR submitted: ${result.pr_url}`, 'success')
        removeOSSReadyToSubmit(item.originSlug, item.branch)
        cancelEditing()

        // Refresh tracking
        const tracking = await getOSSSubmittedTracking()
        if (tracking.success) {
          setSubmittedPRs(tracking.submitted)
        }
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to submit PR', 'error')
    } finally {
      setSubmitting(null)
    }
  }

  if (ossStage5.loading && readyItems.length === 0 && !trackingLoading) {
    return <LoadingState text="Loading..." />
  }

  const hasNoContent = readyItems.length === 0 && submittedPRs.length === 0

  return (
    <div className="stage-panel">
      {/* Ready to Submit Section */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            <span className="stage-section__icon">{'\u{1F4E4}'}</span>
            Ready to Submit ({readyItems.length})
          </h3>
        </div>

        {readyItems.length === 0 ? (
          <EmptyState
            icon="\u{1F4ED}"
            title="Nothing to submit"
            description="Merge PRs on your fork in Stage 4 — they'll appear here for upstream submission."
          />
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Origin Repo</th>
                  <th>Branch</th>
                  <th>PR Title</th>
                  <th>Base Branch</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {readyItems.map((item: ReadyToSubmit) => {
                  const key = `${item.originSlug}-${item.branch}`
                  const isEditing =
                    editingItem?.originSlug === item.originSlug &&
                    editingItem?.branch === item.branch

                  return (
                    <tr key={key}>
                      <td>
                        <span className="repo-link">{item.originSlug}</span>
                      </td>
                      <td className="text-light">{item.branch}</td>
                      <td>{item.title}</td>
                      <td className="text-light">{item.baseBranch}</td>
                      <td>
                        {isEditing ? (
                          <div className="action-buttons">
                            <button
                              className="btn btn--primary btn--sm"
                              onClick={() => {
                                void handleSubmit(item)
                              }}
                              disabled={submitting === key}
                            >
                              {submitting === key ? 'Submitting...' : 'Confirm Submit'}
                            </button>
                            <button
                              className="btn btn--secondary btn--sm"
                              onClick={cancelEditing}
                              disabled={submitting === key}
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            className="btn btn--primary btn--sm"
                            onClick={() => startEditing(item)}
                          >
                            Submit
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Inline PR Editor */}
        {editingItem && (
          <div className="oss-submit-editor">
            <h4>Edit PR before submitting to {editingItem.originSlug}</h4>
            <div className="form-group">
              <label className="filter-label">PR Title</label>
              <input
                type="text"
                className="form-input"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
              />
            </div>
            <div className="form-group">
              <label className="filter-label">PR Body (Markdown)</label>
              <textarea
                className="form-input form-textarea"
                rows={8}
                value={editBody}
                onChange={e => setEditBody(e.target.value)}
              />
            </div>
          </div>
        )}
      </div>

      {/* Submitted PRs Tracking */}
      {(submittedPRs.length > 0 || trackingLoading) && (
        <>
          <hr className="stage-divider" />
          <div className="stage-section">
            <div className="stage-section__header">
              <h3 className="stage-section__title">
                <span className="stage-section__icon">{'\u{1F4CA}'}</span>
                Submitted PRs ({submittedPRs.length})
              </h3>
            </div>

            {trackingLoading ? (
              <LoadingState text="Loading tracking data..." />
            ) : (
              <div className="table-container">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Origin Repo</th>
                      <th>PR</th>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Submitted</th>
                    </tr>
                  </thead>
                  <tbody>
                    {submittedPRs.map((pr: SubmittedPR) => (
                      <tr key={pr.prUrl}>
                        <td>
                          <span className="repo-link">{pr.originSlug}</span>
                        </td>
                        <td>
                          <a
                            href={pr.prUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="issue-link"
                          >
                            View PR
                          </a>
                        </td>
                        <td>{pr.title}</td>
                        <td>
                          <span
                            className={
                              pr.state === 'merged'
                                ? 'badge badge--success'
                                : pr.state === 'closed'
                                  ? 'badge badge--danger'
                                  : 'badge badge--primary'
                            }
                          >
                            {pr.state}
                          </span>
                        </td>
                        <td className="text-light">{formatTimeAgo(pr.submittedAt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {hasNoContent && !ossStage5.loading && !trackingLoading && (
        <EmptyState
          icon="\u{1F4E4}"
          title="No submissions yet"
          description="Complete the fork & assign and review stages first."
        />
      )}
    </div>
  )
}
