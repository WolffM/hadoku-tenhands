/**
 * Stage4Review
 *
 * Review and merge open PRs.
 * Shows ready-for-review PRs and in-progress drafts.
 * Includes a PR detail modal with diff viewer.
 */

import { useState, useMemo, type ReactElement } from 'react'
import { usePipelineStore } from '../../store'
import { getPRDetails, approvePR, mergePR, markPRReady } from '../../api/endpoints'
import type { PullRequest, PRDetails } from '../../api/types'
import { formatTimeAgo, escapeHtml } from '../../utils'
import { DiffViewer } from '../review/DiffViewer'

export function Stage4Review() {
  const stage4 = usePipelineStore(state => state.stage4)
  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const loadStage4 = usePipelineStore(state => state.loadStage4)
  const removeStage4PR = usePipelineStore(state => state.removeStage4PR)

  const [modalOpen, setModalOpen] = useState(false)
  const [currentPR, setCurrentPR] = useState<PRDetails | null>(null)
  const [currentPRIndex, setCurrentPRIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)

  const prs = stage4.items

  // Split PRs into ready and in-progress
  const readyPRs = useMemo(() => prs.filter(pr => isPRReady(pr)), [prs])
  const inProgressPRs = useMemo(() => prs.filter(pr => !isPRReady(pr)), [prs])

  const openPRModal = async (pr: PullRequest, index: number) => {
    if (!owner) return

    setCurrentPRIndex(index)
    setModalOpen(true)
    setLoading(true)

    try {
      const result = await getPRDetails(owner, pr.repo ?? '', pr.number)
      if (result.success && result.pr) {
        setCurrentPR(result.pr)
      } else {
        addLog(`Failed to load PR details: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to load PR details', 'error')
    } finally {
      setLoading(false)
    }
  }

  const closePRModal = () => {
    setModalOpen(false)
    setCurrentPR(null)
  }

  const showNextPR = () => {
    if (currentPRIndex < readyPRs.length - 1) {
      const nextPR = readyPRs[currentPRIndex + 1]
      void openPRModal(nextPR, currentPRIndex + 1)
    } else if (readyPRs.length === 0) {
      closePRModal()
      addLog('All PRs reviewed!', 'success')
    }
  }

  const showPrevPR = () => {
    if (currentPRIndex > 0) {
      const prevPR = readyPRs[currentPRIndex - 1]
      void openPRModal(prevPR, currentPRIndex - 1)
    }
  }

  const handleApprove = async () => {
    if (!owner || !currentPR) return

    setActionLoading(true)
    addLog(`Approving ${currentPR.repo}#${currentPR.number}...`, 'info')

    try {
      const result = await approvePR(owner, currentPR.repo ?? '', currentPR.number)
      if (result.success) {
        addLog(`Approved ${currentPR.repo}#${currentPR.number}`, 'success')
        // Reload to update review status
        void loadStage4()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to approve PR', 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleMerge = async () => {
    if (!owner || !currentPR) return

    setActionLoading(true)
    const prRepo = currentPR.repo ?? ''
    const prNumber = currentPR.number
    addLog(`Merging ${prRepo}#${prNumber}...`, 'info')

    try {
      const result = await mergePR(owner, prRepo, prNumber)
      if (result.success) {
        addLog(`Merged ${prRepo}#${prNumber}`, 'success')
        // Immediately remove from UI
        removeStage4PR(prRepo, prNumber)
        // Move to next PR (if any left)
        showNextPR()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to merge PR', 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const quickApprove = async (pr: PullRequest) => {
    if (!owner) return

    addLog(`Approving ${pr.repo}#${pr.number}...`, 'info')

    try {
      const result = await approvePR(owner, pr.repo ?? '', pr.number)
      if (result.success) {
        addLog(`Approved ${pr.repo}#${pr.number}`, 'success')
        void loadStage4()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to approve PR', 'error')
    }
  }

  const quickMerge = async (pr: PullRequest) => {
    if (!owner) return

    const prRepo = pr.repo ?? ''
    addLog(`Merging ${prRepo}#${pr.number}...`, 'info')

    try {
      const result = await mergePR(owner, prRepo, pr.number)
      if (result.success) {
        addLog(`Merged ${prRepo}#${pr.number}`, 'success')
        // Immediately remove from UI
        removeStage4PR(prRepo, pr.number)
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to merge PR', 'error')
    }
  }

  const handleMarkReady = async (pr: PullRequest) => {
    if (!owner) return

    addLog(`Marking ${pr.repo}#${pr.number} as ready...`, 'info')

    try {
      const result = await markPRReady(owner, pr.repo ?? '', pr.number)
      if (result.success) {
        addLog(`Marked ${pr.repo}#${pr.number} as ready`, 'success')
        void loadStage4()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to mark PR as ready', 'error')
    }
  }

  // Loading state
  if (stage4.loading && prs.length === 0) {
    return (
      <div className="loading-state">
        <div className="loading-state__spinner" />
        <p className="loading-state__text">Loading pull requests...</p>
      </div>
    )
  }

  // Empty state
  if (prs.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">📭</div>
        <h3 className="empty-state__title">No open pull requests</h3>
        <p className="empty-state__description">
          Assign Copilot to issues in Stage 3 to generate PRs.
        </p>
      </div>
    )
  }

  return (
    <div className="stage-panel">
      {/* Ready for Review Section */}
      {readyPRs.length > 0 ? (
        <div className="stage-section stage-section--ready">
          <div className="stage-section__header">
            <h3 className="stage-section__title">
              <span className="stage-section__icon">✅</span>
              Ready for Review ({readyPRs.length})
            </h3>
          </div>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Repo</th>
                  <th>Title</th>
                  <th>Branch</th>
                  <th>Author</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {readyPRs.map((pr, index) => (
                  <PRRow
                    key={`${pr.repo}-${pr.number}`}
                    pr={pr}
                    showReviewStatus
                    isReady
                    onView={() => {
                      void openPRModal(pr, index)
                    }}
                    onApprove={() => {
                      void quickApprove(pr)
                    }}
                    onMerge={() => {
                      void quickMerge(pr)
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="text-secondary stage-section">ℹ️ No PRs ready for review</p>
      )}

      {/* In Progress Section */}
      {inProgressPRs.length > 0 && (
        <>
          <hr className="stage-divider" />
          <div className="stage-section">
            <div className="stage-section__header">
              <h3 className="stage-section__title">
                <span className="stage-section__icon">⏳</span>
                In Progress / Draft ({inProgressPRs.length})
              </h3>
            </div>

            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Repo</th>
                    <th>Title</th>
                    <th>Branch</th>
                    <th>Author</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {inProgressPRs.map((pr, index) => (
                    <PRRow
                      key={`${pr.repo}-${pr.number}`}
                      pr={pr}
                      showReviewStatus={false}
                      isReady={false}
                      onView={() => {
                        void openPRModal(pr, index)
                      }}
                      onMarkReady={() => {
                        void handleMarkReady(pr)
                      }}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* PR Detail Modal */}
      {modalOpen && (
        <PRModal
          pr={currentPR}
          loading={loading}
          actionLoading={actionLoading}
          currentIndex={currentPRIndex}
          totalCount={readyPRs.length}
          onClose={closePRModal}
          onPrev={showPrevPR}
          onNext={showNextPR}
          onApprove={handleApprove}
          onMerge={handleMerge}
        />
      )}
    </div>
  )
}

// Helper to check if PR is ready
function isPRReady(pr: PullRequest): boolean {
  const author = pr.author?.login ?? ''
  const isCopilot = author.toLowerCase().includes('copilot')

  if (isCopilot) {
    return pr.copilotCompleted === true
  }
  return !pr.isDraft
}

interface PRRowProps {
  pr: PullRequest
  showReviewStatus: boolean
  isReady: boolean
  onView: () => void
  onApprove?: () => void
  onMerge?: () => void
  onMarkReady?: () => void
}

function PRRow({
  pr,
  showReviewStatus,
  isReady,
  onView,
  onApprove,
  onMerge,
  onMarkReady
}: PRRowProps) {
  const author = pr.author?.login ?? 'unknown'
  const isCopilot = author.toLowerCase().includes('copilot')

  // Strip [WIP] prefix from title
  let displayTitle = pr.title.replace(/^\[WIP\]\s*/i, '')
  if (displayTitle.length > 40) {
    displayTitle = displayTitle.substring(0, 40) + '...'
  }

  // Build status badges
  const badges: ReactElement[] = []
  if (pr.isDraft) {
    badges.push(
      <span key="draft" className="badge badge--warning">
        Draft
      </span>
    )
  }
  if (isCopilot && pr.copilotCompleted === false) {
    badges.push(
      <span key="wip" className="badge badge--info">
        WIP
      </span>
    )
  }

  // Review status badge
  const getReviewBadge = () => {
    if (pr.reviewDecision === 'APPROVED') {
      return <span className="badge badge--success">Approved</span>
    }
    if (pr.reviewDecision === 'CHANGES_REQUESTED') {
      return <span className="badge badge--danger">Changes</span>
    }
    return <span className="badge badge--secondary">Pending</span>
  }

  return (
    <tr>
      <td>
        <span className="repo-link">{pr.repo}</span>
        <span className="text-secondary">#{pr.number}</span>
      </td>
      <td>
        <a
          href={pr.url}
          target="_blank"
          rel="noopener noreferrer"
          className="pr-link"
          title={pr.title}
        >
          {escapeHtml(displayTitle)}
        </a>
        {badges.length > 0 && <span className="badge-group">{badges}</span>}
      </td>
      <td>
        <code className="branch-name" title={pr.headRefName}>
          {pr.headRefName}
        </code>
      </td>
      <td>
        {isCopilot ? '🤖' : '👤'}{' '}
        <span className="text-secondary">{author.replace('app/', '')}</span>
      </td>
      {showReviewStatus && <td>{getReviewBadge()}</td>}
      <td className="text-secondary">{formatTimeAgo(pr.createdAt)}</td>
      <td>
        <div className="pr-actions">
          <button className="btn btn--ghost btn--sm" onClick={onView} title="View Details">
            👁️
          </button>
          {isReady ? (
            <>
              <button className="btn btn--ghost btn--sm" onClick={onApprove} title="Approve">
                ✅
              </button>
              <button className="btn btn--ghost btn--sm" onClick={onMerge} title="Merge">
                🔀
              </button>
            </>
          ) : (
            <button
              className="btn btn--ghost btn--sm"
              onClick={onMarkReady}
              title="Mark Ready"
              disabled={!pr.isDraft}
            >
              ⏳
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}

interface PRModalProps {
  pr: PRDetails | null
  loading: boolean
  actionLoading: boolean
  currentIndex: number
  totalCount: number
  onClose: () => void
  onPrev: () => void
  onNext: () => void
  onApprove: () => Promise<void>
  onMerge: () => Promise<void>
}

function PRModal({
  pr,
  loading,
  actionLoading,
  currentIndex,
  totalCount,
  onClose,
  onPrev,
  onNext,
  onApprove,
  onMerge
}: PRModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal pr-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal__header">
          <div className="modal__title-section">
            <h2 className="modal__title">{loading ? 'Loading...' : (pr?.title ?? 'PR Details')}</h2>
            {pr && (
              <span className="modal__subtitle">
                {pr.repo} #{pr.number}
              </span>
            )}
          </div>
          <div className="modal__nav">
            <button
              className="btn btn--secondary btn--sm"
              onClick={onPrev}
              disabled={currentIndex <= 0}
            >
              ← Prev
            </button>
            <span className="modal__counter">
              {totalCount > 0 ? `${currentIndex + 1}/${totalCount}` : '0/0'}
            </span>
            <button
              className="btn btn--secondary btn--sm"
              onClick={onNext}
              disabled={currentIndex >= totalCount - 1}
            >
              Next →
            </button>
            <button className="btn btn--ghost btn--sm" onClick={onClose}>
              ✕
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="modal__content">
          {loading ? (
            <div className="loading-state">
              <div className="loading-state__spinner" />
              <p className="loading-state__text">Loading PR details...</p>
            </div>
          ) : pr ? (
            <div className="pr-modal__content">
              {/* Sidebar */}
              <div className="pr-modal__sidebar">
                <div className="pr-info">
                  <div className="pr-info__branch">
                    <span className="badge badge--primary">{pr.headRefName}</span>
                    {pr.isDraft && <span className="badge badge--warning">Draft</span>}
                    <div className="text-secondary">→ {pr.baseRefName}</div>
                  </div>

                  <div className="pr-info__meta">
                    <div>👤 {pr.author?.login ?? 'unknown'}</div>
                    <div>🕐 {formatTimeAgo(pr.createdAt)}</div>
                    <div>📝 {pr.commits ?? 0} commits</div>
                  </div>

                  <div className="pr-info__description">
                    <h4>Description</h4>
                    <div className="pr-description">
                      {pr.body ? escapeHtml(pr.body.substring(0, 500)) : 'No description'}
                      {pr.body && pr.body.length > 500 && '...'}
                    </div>
                  </div>

                  {pr.files && pr.files.length > 0 && (
                    <div className="pr-info__files">
                      <h4>Changed Files</h4>
                      <ul className="file-list">
                        {pr.files.map(file => (
                          <li key={file.path} className="file-list__item">
                            <span className="file-list__name">{file.path.split('/').pop()}</span>
                            <span className="file-list__stats">
                              <span className="text-success">+{file.additions}</span>
                              <span className="text-danger">-{file.deletions}</span>
                            </span>
                          </li>
                        ))}
                      </ul>
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

              {/* Diff Viewer */}
              <div className="pr-modal__diff">
                <div className="pr-stats">
                  <span className="text-success">+{pr.additions ?? 0}</span>{' '}
                  <span className="text-danger">-{pr.deletions ?? 0}</span> in{' '}
                  {pr.changedFiles ?? pr.files?.length ?? 0} files
                </div>
                {pr.diff ? (
                  <DiffViewer diff={pr.diff} />
                ) : (
                  <p className="text-secondary">No diff available</p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-danger">Failed to load PR details</p>
          )}
        </div>

        {/* Footer */}
        <div className="modal__footer">
          <button className="btn btn--secondary" onClick={onClose}>
            Close
          </button>
          <div className="modal__actions">
            <button
              className="btn btn--success"
              onClick={() => {
                void onApprove()
              }}
              disabled={loading || actionLoading || !pr}
            >
              {actionLoading ? 'Approving...' : 'Approve'}
            </button>
            <button
              className="btn btn--primary"
              onClick={() => {
                void onMerge()
              }}
              disabled={loading || actionLoading || !pr}
            >
              {actionLoading ? 'Merging...' : 'Merge'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
