/**
 * ReviewQueueView
 *
 * View for reviewing items that need human review.
 */

import { useEffect } from 'react'
import { usePipelineStore, useReviewQueueStore, selectItemsAwaitingReview } from '../store'
import { ReviewCarousel } from '../components/review'
import { ProgressLog } from '../components/common'

export function ReviewQueueView() {
  const itemsAwaitingReview = usePipelineStore(selectItemsAwaitingReview)
  const loadStage4 = usePipelineStore(state => state.loadStage4)
  const stage4Loading = usePipelineStore(state => state.stage4.loading)
  const stage4LastFetched = usePipelineStore(state => state.stage4.lastFetched)
  const setQueue = useReviewQueueStore(state => state.setQueue)

  // Load stage 4 data on mount if not already loaded
  useEffect(() => {
    if (!stage4Loading && !stage4LastFetched) {
      void loadStage4()
    }
  }, [loadStage4, stage4Loading, stage4LastFetched])

  // Sync pipeline items awaiting review to the review queue
  useEffect(() => {
    // Update queue when items change
    if (itemsAwaitingReview.length > 0) {
      setQueue(itemsAwaitingReview)
    }
  }, [itemsAwaitingReview, setQueue])

  return (
    <div className="review-queue-view">
      <ReviewCarousel />
      <ProgressLog />
    </div>
  )
}
