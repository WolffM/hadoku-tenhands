/**
 * ReviewCarousel Component
 *
 * Carousel for reviewing pipeline items that need human review.
 */

import { useEffect, useState } from 'react'
import type { PullRequest } from '../../api/types'
import {
  usePipelineStore,
  useReviewQueueStore,
  selectCurrentItem,
  selectQueuePosition,
  selectHasNext,
  selectHasPrevious,
  selectIsQueueEmpty
} from '../../store'
import { approvePR, mergePR } from '../../api/endpoints'
import { DiffViewer } from './DiffViewer'
import { ReviewActions } from './ReviewActions'

export function ReviewCarousel() {
  const [actionLoading, setActionLoading] = useState(false)

  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const loadStage4 = usePipelineStore(state => state.loadStage4)

  const currentItem = useReviewQueueStore(selectCurrentItem)
  const position = useReviewQueueStore(selectQueuePosition)
  const hasNext = useReviewQueueStore(selectHasNext)
  const hasPrevious = useReviewQueueStore(selectHasPrevious)
  const isEmpty = useReviewQueueStore(selectIsQueueEmpty)

  const goToNext = useReviewQueueStore(state => state.goToNext)
  const goToPrevious = useReviewQueueStore(state => state.goToPrevious)
  const loadCurrentDetails = useReviewQueueStore(state => state.loadCurrentDetails)
  const removeCurrentFromQueue = useReviewQueueStore(state => state.removeCurrentFromQueue)

  const currentDetails = useReviewQueueStore(state => state.currentDetails)
  const detailsLoading = useReviewQueueStore(state => state.detailsLoading)
  const detailsError = useReviewQueueStore(state => state.detailsError)

  // Load details when current item changes
  useEffect(() => {
    if (currentItem && owner) {
      void loadCurrentDetails(owner)
    }
  }, [currentItem?.id, owner, loadCurrentDetails])

  if (isEmpty) {
    return (
      <div className="review-carousel review-carousel-empty">
        <div className="empty-state">
          <h3>No items to review</h3>
          <p>All pipeline items have been reviewed or are still processing.</p>
        </div>
      </div>
    )
  }

  if (!currentItem) {
    return null
  }

  const pr = currentItem.id.startsWith('pr-') ? (currentItem.data as PullRequest) : null

  const handleApprove = async () => {
    if (!owner || !pr) return
    setActionLoading(true)
    try {
      const result = await approvePR(owner, currentItem.repo, pr.number)
      if (result.success) {
        addLog(`Approved PR ${currentItem.repo}#${pr.number}`, 'success')
        removeCurrentFromQueue()
        await loadStage4()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch (err) {
      addLog(`Error: ${err instanceof Error ? err.message : 'Unknown'}`, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleMerge = async () => {
    if (!owner || !pr) return
    setActionLoading(true)
    try {
      const result = await mergePR(owner, currentItem.repo, pr.number)
      if (result.success) {
        addLog(`Merged PR ${currentItem.repo}#${pr.number}`, 'success')
        removeCurrentFromQueue()
        await loadStage4()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch (err) {
      addLog(`Error: ${err instanceof Error ? err.message : 'Unknown'}`, 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSkip = () => {
    if (hasNext) {
      goToNext()
    }
  }

  const handleYolo = () => {
    addLog('Yolo mode not yet implemented', 'warning')
  }

  return (
    <div className="review-carousel">
      {/* Header with navigation */}
      <div className="review-carousel-header">
        <div className="review-nav">
          <button
            className="nav-btn nav-btn-prev"
            onClick={goToPrevious}
            disabled={!hasPrevious}
            title="Previous item"
          >
            ←
          </button>
          <span className="nav-position">
            {position.current} / {position.total}
          </span>
          <button
            className="nav-btn nav-btn-next"
            onClick={goToNext}
            disabled={!hasNext}
            title="Next item"
          >
            →
          </button>
        </div>

        <div className="review-item-info">
          <span className="review-repo">{currentItem.repo}</span>
          <span className="review-separator">/</span>
          <span className="review-identifier">{currentItem.identifier}</span>
          {pr && (
            <a href={pr.url} target="_blank" rel="noopener noreferrer" className="review-link">
              View on GitHub
            </a>
          )}
        </div>
      </div>

      {/* Title */}
      {pr && (
        <div className="review-title">
          <h2>{pr.title}</h2>
          <div className="review-meta">
            <span>by {pr.author?.login || 'Unknown'}</span>
            <span className="meta-separator">•</span>
            <span>
              {pr.headRefName} → {pr.baseRefName}
            </span>
            {pr.isDraft && (
              <>
                <span className="meta-separator">•</span>
                <span className="meta-draft">Draft</span>
              </>
            )}
          </div>
        </div>
      )}

      {/* Diff content */}
      <div className="review-content">
        {detailsLoading && (
          <div className="loading-state">
            <p>Loading diff...</p>
          </div>
        )}
        {detailsError && (
          <div className="error-state">
            <p>Error loading details: {detailsError}</p>
          </div>
        )}
        {currentDetails?.diff && !detailsLoading && <DiffViewer diff={currentDetails.diff} />}
        {!currentDetails?.diff && !detailsLoading && !detailsError && (
          <div className="no-diff-state">
            <p>No diff available</p>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="review-footer">
        <ReviewActions
          onApprove={() => {
            void handleApprove()
          }}
          onMerge={() => {
            void handleMerge()
          }}
          onSkip={handleSkip}
          onYolo={handleYolo}
          loading={actionLoading}
          canMerge={pr !== null && !pr.isDraft}
        />
      </div>
    </div>
  )
}
