/**
 * OSSReviewPanel — Stage 4
 *
 * Review and merge PRs on forked repos.
 * Shows ready-for-review PRs and in-progress drafts.
 * Includes a PR detail modal with diff viewer.
 */

import { useState, useMemo, useCallback } from 'react'
import { usePipelineStore } from '../../store'
import { getOSSForkPRDetails, approveOSSForkPR, mergeOSSForkPR } from '../../api/endpoints'
import type { ForkPR, PRDetails } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'
import { PRModal } from '../review/PRModal'

export function OSSReviewPanel() {
  const ossStage4 = usePipelineStore(state => state.ossStage4)
  const addLog = usePipelineStore(state => state.addLog)
  const loadOSSStage4 = usePipelineStore(state => state.loadOSSStage4)
  const loadOSSStage5 = usePipelineStore(state => state.loadOSSStage5)
  const removeOSSForkPR = usePipelineStore(state => state.removeOSSForkPR)

  const [modalOpen, setModalOpen] = useState(false)
  const [currentPR, setCurrentPR] = useState<PRDetails | null>(null)
  const [currentPRIndex, setCurrentPRIndex] = useState(0)
  const [detailLoading, setDetailLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState(false)

  const prs = ossStage4.items

  // Split PRs into ready and in-progress
  const readyPRs = useMemo(() => prs.filter(pr => !pr.isDraft), [prs])
  const inProgressPRs = useMemo(() => prs.filter(pr => pr.isDraft), [prs])

  const openPRModal = useCallback(
    async (pr: ForkPR, index: number) => {
      setCurrentPRIndex(index)
      setModalOpen(true)
      setDetailLoading(true)

      try {
        const result = await getOSSForkPRDetails(pr.repo, pr.number)
        if (result.success && result.pr) {
          setCurrentPR(result.pr)
        } else {
          addLog(`Failed to load PR details: ${result.error}`, 'error')
        }
      } catch {
        addLog('Failed to load PR details', 'error')
      } finally {
        setDetailLoading(false)
      }
    },
    [addLog]
  )

  const closePRModal = () => {
    setModalOpen(false)
    setCurrentPR(null)
  }

  const showNextPR = () => {
    if (currentPRIndex < readyPRs.length - 1) {
      void openPRModal(readyPRs[currentPRIndex + 1], currentPRIndex + 1)
    } else {
      closePRModal()
    }
  }

  const showPrevPR = () => {
    if (currentPRIndex > 0) {
      void openPRModal(readyPRs[currentPRIndex - 1], currentPRIndex - 1)
    }
  }

  const handleApprove = async (repo: string, prNumber: number) => {
    setActionLoading(true)
    addLog(`Approving ${repo} PR #${prNumber}...`, 'info')

    try {
      const result = await approveOSSForkPR(repo, prNumber)
      if (result.success) {
        addLog(`Approved ${repo} PR #${prNumber}`, 'success')
        void loadOSSStage4()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to approve PR', 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleMerge = async (repo: string, prNumber: number, originSlug: string) => {
    setActionLoading(true)
    addLog(`Merging ${repo} PR #${prNumber}...`, 'info')

    try {
      const result = await mergeOSSForkPR(repo, prNumber, originSlug)
      if (result.success) {
        addLog(`Merged ${repo} PR #${prNumber} — ready for upstream submission`, 'success')
        removeOSSForkPR(repo, prNumber)
        void loadOSSStage5()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to merge PR', 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleModalApprove = async () => {
    if (!currentPR) return
    await handleApprove(currentPR.repo ?? '', currentPR.number)
  }

  const handleModalMerge = async () => {
    if (!currentPR) return
    // Find the fork PR to get originSlug
    const forkPR = prs.find(p => p.number === currentPR.number && p.repo === (currentPR.repo ?? ''))
    await handleMerge(currentPR.repo ?? '', currentPR.number, forkPR?.originSlug ?? '')
    showNextPR()
  }

  if (ossStage4.loading && prs.length === 0) {
    return <LoadingState text="Loading fork PRs..." />
  }

  if (prs.length === 0) {
    return (
      <EmptyState
        icon="\u{1F4ED}"
        title="No fork PRs"
        description="Assign Copilot to issues in Stage 3 — PRs will appear here once the agent creates them."
      />
    )
  }

  return (
    <div className="stage-panel">
      {/* Ready for Review */}
      {readyPRs.length > 0 ? (
        <div className="stage-section stage-section--ready">
          <div className="stage-section__header">
            <h3 className="stage-section__title">
              <span className="stage-section__icon">{'\u2705'}</span>
              Ready for Review ({readyPRs.length})
            </h3>
          </div>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Fork Repo</th>
                  <th>PR</th>
                  <th>Title</th>
                  <th>Branch</th>
                  <th>Changes</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {readyPRs.map((pr, index) => (
                  <ForkPRRow
                    key={`${pr.repo}-${pr.number}`}
                    pr={pr}
                    onView={() => {
                      void openPRModal(pr, index)
                    }}
                    onApprove={() => {
                      void handleApprove(pr.repo, pr.number)
                    }}
                    onMerge={() => {
                      void handleMerge(pr.repo, pr.number, pr.originSlug)
                    }}
                    actionLoading={actionLoading}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="text-secondary stage-section">{'\u2139\uFE0F'} No PRs ready for review</p>
      )}

      {/* In Progress */}
      {inProgressPRs.length > 0 && (
        <>
          <hr className="stage-divider" />
          <div className="stage-section">
            <div className="stage-section__header">
              <h3 className="stage-section__title">
                <span className="stage-section__icon">{'\u23F3'}</span>
                In Progress / Draft ({inProgressPRs.length})
              </h3>
            </div>

            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Fork Repo</th>
                    <th>PR</th>
                    <th>Title</th>
                    <th>Branch</th>
                    <th>Changes</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {inProgressPRs.map((pr, index) => (
                    <ForkPRRow
                      key={`${pr.repo}-${pr.number}`}
                      pr={pr}
                      onView={() => {
                        void openPRModal(pr, index)
                      }}
                      actionLoading={actionLoading}
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
          loading={detailLoading}
          actionLoading={actionLoading}
          currentIndex={currentPRIndex}
          totalCount={readyPRs.length}
          onClose={closePRModal}
          onPrev={showPrevPR}
          onNext={showNextPR}
          onApprove={handleModalApprove}
          onMerge={handleModalMerge}
        />
      )}
    </div>
  )
}

// ============ Fork PR Row ============

interface ForkPRRowProps {
  pr: ForkPR
  onView: () => void
  onApprove?: () => void
  onMerge?: () => void
  actionLoading: boolean
}

function ForkPRRow({ pr, onView, onApprove, onMerge, actionLoading }: ForkPRRowProps) {
  const displayTitle = pr.title.length > 40 ? pr.title.substring(0, 40) + '...' : pr.title
  const reviewBadge =
    pr.reviewDecision === 'APPROVED'
      ? 'badge badge--success'
      : pr.reviewDecision === 'CHANGES_REQUESTED'
        ? 'badge badge--danger'
        : 'badge badge--secondary'

  return (
    <tr>
      <td>
        <span className="repo-link">{pr.repo}</span>
      </td>
      <td className="text-light">#{pr.number}</td>
      <td>
        <a
          href={pr.url}
          target="_blank"
          rel="noopener noreferrer"
          className="issue-link"
          title={pr.title}
        >
          {displayTitle}
        </a>
      </td>
      <td className="text-light">{pr.headRefName}</td>
      <td className="text-light">
        <span className="text-success">+{pr.additions}</span>
        {' / '}
        <span className="text-danger">-{pr.deletions}</span> ({pr.changedFiles} files)
      </td>
      {!pr.isDraft && (
        <td>
          <span className={reviewBadge}>{pr.reviewDecision || 'pending'}</span>
        </td>
      )}
      <td className="text-light">{formatTimeAgo(pr.createdAt)}</td>
      <td>
        <div className="action-buttons">
          <button className="btn btn--secondary btn--sm" onClick={onView}>
            View
          </button>
          {onApprove && (
            <button
              className="btn btn--primary btn--sm"
              onClick={onApprove}
              disabled={actionLoading}
            >
              Approve
            </button>
          )}
          {onMerge && (
            <button className="btn btn--warning btn--sm" onClick={onMerge} disabled={actionLoading}>
              Merge
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
