/**
 * ReviewQueueView
 *
 * View for reviewing items that need human review.
 */

import { useEffect, useRef, useMemo } from 'react'
import { usePipelineStore, useReviewQueueStore } from '../store'
import { ReviewCarousel } from '../components/review'
import { ProgressLog } from '../components/common'

export function ReviewQueueView() {
  // Get pipeline items and filter for those awaiting review
  // Using useMemo to stabilize the filtered array reference
  const pipelineItems = usePipelineStore(state => state.pipelineItems)
  const itemsAwaitingReview = useMemo(
    () => pipelineItems.filter(item => item.status === 'waiting_for_review'),
    [pipelineItems]
  )

  const loadStage4 = usePipelineStore(state => state.loadStage4)
  const stage4Loading = usePipelineStore(state => state.stage4.loading)
  const stage4LastFetched = usePipelineStore(state => state.stage4.lastFetched)
  const setQueue = useReviewQueueStore(state => state.setQueue)

  // Track previous item IDs to avoid unnecessary queue updates
  const prevItemIdsRef = useRef<string>('')

  // Load stage 4 data on mount if not already loaded
  useEffect(() => {
    if (!stage4Loading && !stage4LastFetched) {
      void loadStage4()
    }
  }, [loadStage4, stage4Loading, stage4LastFetched])

  // Sync pipeline items awaiting review to the review queue
  // Only sync after stage 4 data has been loaded and items actually changed
  useEffect(() => {
    if (!stage4LastFetched) return

    // Create a stable string of item IDs to compare
    const currentItemIds = itemsAwaitingReview.map(item => item.id).join(',')

    // Only update queue if items actually changed
    if (currentItemIds !== prevItemIdsRef.current) {
      prevItemIdsRef.current = currentItemIds
      setQueue(itemsAwaitingReview)
    }
  }, [itemsAwaitingReview, setQueue, stage4LastFetched])

  return (
    <div className="review-queue-view">
      <ReviewCarousel isLoading={stage4Loading && !stage4LastFetched} />
      <ProgressLog />
    </div>
  )
}
