/**
 * TaskAutoReviewModal
 *
 * The in-app replacement for "Review diff" opening a GitHub tab: the PR's
 * diff next to the plan the human approved, and the two actions a taskauto
 * PR actually needs — merge, or send the task back to `stalled` with a
 * reason. Reuses `DiffViewer` for the diff itself and the shared modal
 * chrome (`pr-modal.css`) for the rest; the action set here (merge /
 * send-back-with-reason) doesn't match `PRModal`'s (approve / merge), so
 * this is its own small composition rather than a strained reuse of that one.
 */

import { useEffect, useMemo, useState } from 'react'
import { getTaskAutoPRDetails, mergeTaskAutoPR, sendTaskAutoPRBack } from '../../api'
import type { TaskAutoPR, TaskAutoPRDetails } from '../../api/types'
import { formatTimeAgo, renderMarkdown } from '../../utils'
import { DiffViewer } from '../review/DiffViewer'

export interface TaskAutoReviewModalProps {
  pr: TaskAutoPR
  taskTitle?: string
  onClose: () => void
  /** Board state changed underneath us (merged, or sent back) — refresh the page. */
  onChanged: () => void
}

export function TaskAutoReviewModal({ pr, taskTitle, onClose, onChanged }: TaskAutoReviewModalProps) {
  const [details, setDetails] = useState<TaskAutoPRDetails | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [merging, setMerging] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  const [reasonOpen, setReasonOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [sendingBack, setSendingBack] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    getTaskAutoPRDetails(pr.repo, pr.number)
      .then(data => {
        if (!cancelled) setDetails(data)
      })
      .catch(e => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [pr.repo, pr.number])

  const planHtml = useMemo(
    () => (details?.taskNotes ? renderMarkdown(details.taskNotes) : ''),
    [details?.taskNotes]
  )

  const busy = merging || sendingBack

  const runMerge = async () => {
    setMerging(true)
    setActionError(null)
    try {
      const res = await mergeTaskAutoPR(pr.repo, pr.number)
      if (!res.success) throw new Error(res.error || 'Merge failed')
      onChanged()
      onClose()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setMerging(false)
    }
  }

  const runSendBack = async () => {
    if (!reason.trim()) return
    setSendingBack(true)
    setActionError(null)
    try {
      const res = await sendTaskAutoPRBack(pr.repo, pr.number, reason.trim())
      if (!res.success) throw new Error(res.error || 'Send back failed')
      onChanged()
      onClose()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setSendingBack(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal pr-modal" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <div className="modal__title-section">
            <h2 className="modal__title">{loading ? 'Loading…' : (details?.title ?? pr.title)}</h2>
            <span className="modal__subtitle">
              {pr.repo} #{pr.number}
            </span>
          </div>
          <div className="modal__nav">
            <button className="btn btn--ghost btn--sm" onClick={onClose}>
              ✕
            </button>
          </div>
        </div>

        <div className="modal__content">
          {loading ? (
            <div className="loading-state">
              <div className="loading-state__spinner" />
              <p className="loading-state__text">Loading PR details…</p>
            </div>
          ) : loadError ? (
            <p className="text-danger">{loadError}</p>
          ) : (
            <div className="pr-modal__content">
              <div className="pr-modal__sidebar">
                <div className="pr-info">
                  <div className="pr-info__branch">
                    <span className="badge badge--primary">{details?.headRefName}</span>
                    {details?.isDraft && <span className="badge badge--warning">Draft</span>}
                    <div className="text-secondary">→ {details?.baseRefName}</div>
                  </div>

                  <div className="pr-info__meta">
                    <div>👤 {details?.author?.login ?? 'unknown'}</div>
                    <div>🕐 {details ? formatTimeAgo(details.createdAt) : ''}</div>
                    <div>📝 {details?.commits ?? 0} commits</div>
                  </div>

                  {(taskTitle || details?.taskTitle) && (
                    <div className="pr-info__description">
                      <h4>Task</h4>
                      <div className="pr-description">{taskTitle ?? details?.taskTitle}</div>
                    </div>
                  )}

                  {details?.taskNotes && (
                    <div className="pr-info__description">
                      <h4>Plan</h4>
                      <div
                        className="pr-description"
                        style={{ maxHeight: '320px' }}
                        dangerouslySetInnerHTML={{ __html: planHtml }}
                      />
                    </div>
                  )}

                  <a
                    href={pr.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn--secondary btn--sm"
                    style={{ width: '100%' }}
                  >
                    View on GitHub
                  </a>
                </div>
              </div>

              <div className="pr-modal__diff">
                <div className="pr-stats">
                  <span className="text-success">+{details?.additions ?? 0}</span>{' '}
                  <span className="text-danger">-{details?.deletions ?? 0}</span> in{' '}
                  {details?.changedFiles ?? 0} files
                </div>
                {details?.diff ? <DiffViewer diff={details.diff} /> : <p className="text-secondary">No diff available</p>}
              </div>
            </div>
          )}
        </div>

        <div className="modal__footer">
          <div>
            {actionError && <span className="text-danger">{actionError}</span>}
            {reasonOpen && (
              <textarea
                className="taskauto-review__reason"
                placeholder="Why is this going back? (visible to whoever picks it up next)"
                value={reason}
                onChange={e => setReason(e.target.value)}
                rows={2}
                autoFocus
              />
            )}
          </div>
          <div className="modal__actions">
            {reasonOpen ? (
              <>
                <button
                  className="btn btn--secondary"
                  onClick={() => {
                    setReasonOpen(false)
                    setReason('')
                  }}
                  disabled={busy}
                >
                  Cancel
                </button>
                <button
                  className="btn btn--danger"
                  onClick={() => {
                    void runSendBack()
                  }}
                  disabled={busy || !reason.trim()}
                >
                  {sendingBack ? 'Sending back…' : 'Confirm send back'}
                </button>
              </>
            ) : (
              <>
                <button className="btn btn--ghost" onClick={() => setReasonOpen(true)} disabled={busy || loading}>
                  Send back
                </button>
                <button
                  className="btn btn--primary"
                  onClick={() => {
                    void runMerge()
                  }}
                  disabled={busy || loading || !details}
                >
                  {merging ? 'Merging…' : 'Merge'}
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
