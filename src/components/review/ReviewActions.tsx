/**
 * ReviewActions Component
 *
 * Action buttons for review carousel.
 */

interface ReviewActionsProps {
  onApprove: () => void
  onMerge: () => void
  onSkip: () => void
  onYolo: () => void
  loading?: boolean
  canMerge?: boolean
}

export function ReviewActions({
  onApprove,
  onMerge,
  onSkip,
  onYolo,
  loading = false,
  canMerge = true
}: ReviewActionsProps) {
  return (
    <div className="review-actions">
      <div className="review-actions-primary">
        <button
          className="action-btn action-btn-primary"
          onClick={onApprove}
          disabled={loading}
          title="Approve and go to next item"
        >
          {loading ? 'Processing...' : 'Approve & Next'}
        </button>
        <button
          className="action-btn action-btn-success"
          onClick={onMerge}
          disabled={loading || !canMerge}
          title="Merge and go to next item"
        >
          {loading ? 'Processing...' : 'Merge & Next'}
        </button>
      </div>
      <div className="review-actions-secondary">
        <button
          className="action-btn action-btn-ghost"
          onClick={onSkip}
          disabled={loading}
          title="Skip to next item without action"
        >
          Skip
        </button>
        <button
          className="action-btn action-btn-warning"
          onClick={onYolo}
          disabled={loading}
          title="Skip all remaining reviews"
        >
          Yolo All
        </button>
      </div>
    </div>
  )
}
