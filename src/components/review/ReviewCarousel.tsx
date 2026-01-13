/**
 * ReviewCarousel Component
 *
 * Carousel for reviewing pipeline items that need human review.
 */

import { useEffect, useState, useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { PullRequest } from '../../api/types'

// Configure marked for GitHub-flavored markdown
marked.setOptions({
  gfm: true,
  breaks: true
})
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
import { approvePR, mergePR, markPRReady } from '../../api/endpoints'
import { DiffViewer } from './DiffViewer'
import { ReviewActions } from './ReviewActions'

interface ReviewCarouselProps {
  isLoading?: boolean
}

export function ReviewCarousel({ isLoading = false }: ReviewCarouselProps) {
  const [actionLoading, setActionLoading] = useState(false)

  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const loadStage4 = usePipelineStore(state => state.loadStage4)

  const currentItem = useReviewQueueStore(selectCurrentItem)
  const positionCurrent = useReviewQueueStore(selectQueueCurrentIndex)
  const positionTotal = useReviewQueueStore(selectQueueTotal)
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

  // Render markdown description with memoization
  const renderedDescription = useMemo(() => {
    if (!currentDetails?.body) return null
    const rawHtml = marked.parse(currentDetails.body) as string
    return DOMPurify.sanitize(rawHtml)
  }, [currentDetails?.body])

  // Load details when current item changes
  useEffect(() => {
    if (currentItem && owner) {
      void loadCurrentDetails(owner)
    }
  }, [currentItem?.id, owner, loadCurrentDetails])

  // Show loading state while data is being fetched
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

  const pr = currentItem.id.startsWith('pr-') ? (currentItem.data as PullRequest) : null

  // Single merge handler that does: mark ready (if draft) -> approve -> merge
  const handleMerge = async () => {
    if (!owner || !pr) return
    setActionLoading(true)
    const prRef = `${currentItem.repo}#${pr.number}`

    try {
      // Step 1: Mark as ready if it's a draft
      if (pr.isDraft) {
        addLog(`Marking ${prRef} as ready...`, 'info')
        const readyResult = await markPRReady(owner, currentItem.repo, pr.number)
        if (!readyResult.success) {
          addLog(`Failed to mark ready: ${readyResult.error}`, 'error')
          return
        }
        addLog(`Marked ${prRef} as ready`, 'success')
      }

      // Step 2: Approve the PR
      addLog(`Approving ${prRef}...`, 'info')
      const approveResult = await approvePR(owner, currentItem.repo, pr.number)
      if (!approveResult.success) {
        addLog(`Failed to approve: ${approveResult.error}`, 'error')
        return
      }
      addLog(`Approved ${prRef}`, 'success')

      // Step 3: Merge the PR
      addLog(`Merging ${prRef}...`, 'info')
      const mergeResult = await mergePR(owner, currentItem.repo, pr.number)
      if (mergeResult.success) {
        addLog(`Merged ${prRef}`, 'success')
        // Reset loading state BEFORE removing from queue to avoid stuck button on next item
        setActionLoading(false)
        removeCurrentFromQueue()
        await loadStage4()
      } else {
        addLog(`Failed to merge: ${mergeResult.error}`, 'error')
        setActionLoading(false)
      }
    } catch (err) {
      addLog(`Error: ${err instanceof Error ? err.message : 'Unknown'}`, 'error')
      setActionLoading(false)
    }
  }

  const handleSkip = () => {
    if (hasNext) {
      goToNext()
    }
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
            {positionCurrent} / {positionTotal}
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

      {/* PR Description (Copilot response) */}
      {renderedDescription && !detailsLoading && (
        <div className="review-description">
          <h4 className="review-description__title">Description</h4>
          <div
            className="review-description__content markdown-content"
            dangerouslySetInnerHTML={{ __html: renderedDescription }}
          />
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
          onMerge={() => {
            void handleMerge()
          }}
          onSkip={handleSkip}
          loading={actionLoading}
        />
      </div>
    </div>
  )
}
