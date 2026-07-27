/**
 * ReviewQueueShell
 *
 * Generic navigation shell for the review queue carousel.
 * Handles queue navigation (prev/next), position display,
 * loading/empty states, and detail loading. Delegates item-specific
 * rendering to the children render function.
 */

import { useEffect, type ReactNode } from 'react'
import type { PipelineItem, PRDetails } from '../../api/types'
import {
  usePipelineStore,
  useReviewQueueStore,
  selectCurrentItem,
  selectQueueCurrentIndex,
  selectQueueTotal,
  selectHasNext,
  selectHasPrevious,
  selectIsQueueEmpty
} from '../../store'

interface ReviewQueueShellProps {
  isLoading?: boolean
  children: (
    currentItem: PipelineItem,
    currentDetails: PRDetails | null,
    detailsLoading: boolean
  ) => ReactNode
}

export function ReviewQueueShell({ isLoading = false, children }: ReviewQueueShellProps) {
  const owner = usePipelineStore(state => state.owner)

  const currentItem = useReviewQueueStore(selectCurrentItem)
  const positionCurrent = useReviewQueueStore(selectQueueCurrentIndex)
  const positionTotal = useReviewQueueStore(selectQueueTotal)
  const hasNext = useReviewQueueStore(selectHasNext)
  const hasPrevious = useReviewQueueStore(selectHasPrevious)
  const isEmpty = useReviewQueueStore(selectIsQueueEmpty)

  const goToNext = useReviewQueueStore(state => state.goToNext)
  const goToPrevious = useReviewQueueStore(state => state.goToPrevious)
  const loadCurrentDetails = useReviewQueueStore(state => state.loadCurrentDetails)

  const currentDetails = useReviewQueueStore(state => state.currentDetails)
  const detailsLoading = useReviewQueueStore(state => state.detailsLoading)
  const detailsError = useReviewQueueStore(state => state.detailsError)

  // Load details when current item changes
  useEffect(() => {
    if (currentItem && owner) {
      void loadCurrentDetails(owner)
    }
  }, [currentItem?.id, owner, loadCurrentDetails])

  if (isLoading) {
    return (
      <div className="review-carousel review-carousel-loading">
        <div className="loading-state">
          <p>Loading review queue...</p>
        </div>
      </div>
    )
  }

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
            &larr;
          </button>
          <span className="nav-position">
            {positionCurrent} / {positionTotal}
          </span>
          <button
            className="nav-btn nav-btn-next"
            onClick={goToNext}
            disabled={!hasNext}
            title="Next item"
          >
            &rarr;
          </button>
        </div>

        <div className="review-item-info">
          <span className="review-repo">{currentItem.repo}</span>
          <span className="review-separator">/</span>
          <span className="review-identifier">{currentItem.identifier}</span>
        </div>
      </div>

      {/* Details loading/error */}
      {detailsError && (
        <div className="review-content">
          <div className="error-state">
            <p>Error loading details: {detailsError}</p>
          </div>
        </div>
      )}

      {/* Workflow-specific content */}
      {children(currentItem, currentDetails, detailsLoading)}
    </div>
  )
}
