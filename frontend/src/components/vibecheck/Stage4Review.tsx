/**
 * Stage4Review
 *
 * Review and merge open PRs.
 * Shows ready-for-review PRs and in-progress drafts.
 * Includes a PR detail modal with diff viewer.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { getPRDetails, approvePR, mergePR, markPRReady } from '../../api/endpoints'
import type { PullRequest, PRDetails } from '../../api/types'
import { isPRReady } from '../../utils'
import { PRRow } from '../review/PRRow'
import { PRModal } from '../review/PRModal'

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
