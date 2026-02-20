/**
 * ReviewCarousel Component
 *
 * Carousel for reviewing pipeline items that need human review.
 * Uses ReviewQueueShell for navigation and renders PR-specific content.
 */

import { useState, useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { PipelineItem, PRDetails, PullRequest } from '../../api/types'

// Configure marked for GitHub-flavored markdown
marked.setOptions({
  gfm: true,
  breaks: true
})
import { usePipelineStore, useReviewQueueStore, selectHasNext } from '../../store'
import { approvePR, mergePR, markPRReady } from '../../api/endpoints'
import { getErrorMessage } from '../../utils'
import { DiffViewer } from './DiffViewer'
import { ReviewActions } from './ReviewActions'
import { ReviewQueueShell } from './ReviewQueueShell'

interface ReviewCarouselProps {
  isLoading?: boolean
}

export function ReviewCarousel({ isLoading = false }: ReviewCarouselProps) {
  return (
    <ReviewQueueShell isLoading={isLoading}>
      {(currentItem, currentDetails, detailsLoading) => (
        <PRReviewContent
          currentItem={currentItem}
          currentDetails={currentDetails}
          detailsLoading={detailsLoading}
        />
      )}
    </ReviewQueueShell>
  )
}

interface PRReviewContentProps {
  currentItem: PipelineItem
  currentDetails: PRDetails | null
  detailsLoading: boolean
}

function PRReviewContent({ currentItem, currentDetails, detailsLoading }: PRReviewContentProps) {
  const [actionLoading, setActionLoading] = useState(false)

  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const loadStage4 = usePipelineStore(state => state.loadStage4)

  const hasNext = useReviewQueueStore(selectHasNext)
  const goToNext = useReviewQueueStore(state => state.goToNext)
  const removeCurrentFromQueue = useReviewQueueStore(state => state.removeCurrentFromQueue)

  const pr = currentItem.id.startsWith('pr-') ? (currentItem.data as PullRequest) : null

  // Render markdown description with memoization
  const renderedDescription = useMemo(() => {
    if (!currentDetails?.body) return null
    const rawHtml = marked.parse(currentDetails.body) as string
    return DOMPurify.sanitize(rawHtml)
  }, [currentDetails?.body])

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
      addLog(`Error: ${getErrorMessage(err)}`, 'error')
      setActionLoading(false)
    }
  }

  const handleSkip = () => {
    if (hasNext) {
      goToNext()
    }
  }

  return (
    <>
      {/* GitHub link */}
      {pr && (
        <div className="review-carousel-header" style={{ borderTop: 'none', paddingTop: 0 }}>
          <div className="review-item-info">
            <a href={pr.url} target="_blank" rel="noopener noreferrer" className="review-link">
              View on GitHub
            </a>
          </div>
        </div>
      )}

      {/* Title */}
      {pr && (
        <div className="review-title">
          <h2>{pr.title}</h2>
          <div className="review-meta">
            <span>by {pr.author?.login || 'Unknown'}</span>
            <span className="meta-separator">&bull;</span>
            <span>
              {pr.headRefName} &rarr; {pr.baseRefName}
            </span>
            {pr.isDraft && (
              <>
                <span className="meta-separator">&bull;</span>
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
        {currentDetails?.diff && !detailsLoading && <DiffViewer diff={currentDetails.diff} />}
        {!currentDetails?.diff && !detailsLoading && (
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
    </>
  )
}
