import type { PRDetails } from '../../api/types'
import { formatTimeAgo, escapeHtml } from '../../utils'
import { DiffViewer } from './DiffViewer'

export interface PRModalProps {
  pr: PRDetails | null
  loading: boolean
  actionLoading: boolean
  currentIndex: number
  totalCount: number
  onClose: () => void
  onPrev: () => void
  onNext: () => void
  onApprove: () => Promise<void>
  onMerge: () => Promise<void>
}

export function PRModal({
  pr,
  loading,
  actionLoading,
  currentIndex,
  totalCount,
  onClose,
  onPrev,
  onNext,
  onApprove,
  onMerge
}: PRModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal pr-modal" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal__header">
          <div className="modal__title-section">
            <h2 className="modal__title">{loading ? 'Loading...' : (pr?.title ?? 'PR Details')}</h2>
            {pr && (
              <span className="modal__subtitle">
                {pr.repo} #{pr.number}
              </span>
            )}
          </div>
          <div className="modal__nav">
            <button
              className="btn btn--secondary btn--sm"
              onClick={onPrev}
              disabled={currentIndex <= 0}
            >
              ← Prev
            </button>
            <span className="modal__counter">
              {totalCount > 0 ? `${currentIndex + 1}/${totalCount}` : '0/0'}
            </span>
            <button
              className="btn btn--secondary btn--sm"
              onClick={onNext}
              disabled={currentIndex >= totalCount - 1}
            >
              Next →
            </button>
            <button className="btn btn--ghost btn--sm" onClick={onClose}>
              ✕
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="modal__content">
          {loading ? (
            <div className="loading-state">
              <div className="loading-state__spinner" />
              <p className="loading-state__text">Loading PR details...</p>
            </div>
          ) : pr ? (
            <div className="pr-modal__content">
              {/* Sidebar */}
              <div className="pr-modal__sidebar">
                <div className="pr-info">
                  <div className="pr-info__branch">
                    <span className="badge badge--primary">{pr.headRefName}</span>
                    {pr.isDraft && <span className="badge badge--warning">Draft</span>}
                    <div className="text-secondary">→ {pr.baseRefName}</div>
                  </div>

                  <div className="pr-info__meta">
                    <div>👤 {pr.author?.login ?? 'unknown'}</div>
                    <div>🕐 {formatTimeAgo(pr.createdAt)}</div>
                    <div>📝 {pr.commits ?? 0} commits</div>
                  </div>

                  <div className="pr-info__description">
                    <h4>Description</h4>
                    <div className="pr-description">
                      {pr.body ? escapeHtml(pr.body.substring(0, 500)) : 'No description'}
                      {pr.body && pr.body.length > 500 && '...'}
                    </div>
                  </div>

                  {pr.files && pr.files.length > 0 && (
                    <div className="pr-info__files">
                      <h4>Changed Files</h4>
                      <ul className="file-list">
                        {pr.files.map(file => (
                          <li key={file.path} className="file-list__item">
                            <span className="file-list__name">{file.path.split('/').pop()}</span>
                            <span className="file-list__stats">
                              <span className="text-success">+{file.additions}</span>
                              <span className="text-danger">-{file.deletions}</span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <a
                    href={pr.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn--secondary btn--sm"
                    style={{ width: '100%' }}
                  >
                    View on GitHub
                  </a>
                </div>
              </div>

              {/* Diff Viewer */}
              <div className="pr-modal__diff">
                <div className="pr-stats">
                  <span className="text-success">+{pr.additions ?? 0}</span>{' '}
                  <span className="text-danger">-{pr.deletions ?? 0}</span> in{' '}
                  {pr.changedFiles ?? pr.files?.length ?? 0} files
                </div>
                {pr.diff ? (
                  <DiffViewer diff={pr.diff} />
                ) : (
                  <p className="text-secondary">No diff available</p>
                )}
              </div>
            </div>
          ) : (
            <p className="text-danger">Failed to load PR details</p>
          )}
        </div>

        {/* Footer */}
        <div className="modal__footer">
          <button className="btn btn--secondary" onClick={onClose}>
            Close
          </button>
          <div className="modal__actions">
            <button
              className="btn btn--success"
              onClick={() => {
                void onApprove()
              }}
              disabled={loading || actionLoading || !pr}
            >
              {actionLoading ? 'Approving...' : 'Approve'}
            </button>
            <button
              className="btn btn--primary"
              onClick={() => {
                void onMerge()
              }}
              disabled={loading || actionLoading || !pr}
            >
              {actionLoading ? 'Merging...' : 'Merge'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
