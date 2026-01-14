/**
 * ReviewActions Component
 *
 * Action buttons for review carousel.
 */

interface ReviewActionsProps {
  onMerge: () => void
  onSkip: () => void
  loading?: boolean
}

export function ReviewActions({ onMerge, onSkip, loading = false }: ReviewActionsProps) {
  return (
    <div className="review-actions">
      <div className="review-actions-primary">
        <button
          className="action-btn action-btn-success"
          onClick={onMerge}
          disabled={loading}
          title="Mark ready, approve, and merge"
        >
          {loading ? 'Processing...' : 'Merge'}
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
      </div>
    </div>
  )
}
