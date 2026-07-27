import { type ReactElement } from 'react'
import type { PullRequest } from '../../api/types'
import { formatTimeAgo, escapeHtml } from '../../utils'

export interface PRRowProps {
  pr: PullRequest
  showReviewStatus: boolean
  isReady: boolean
  onView: () => void
  onApprove?: () => void
  onMerge?: () => void
  onMarkReady?: () => void
}

export function PRRow({
  pr,
  showReviewStatus,
  isReady,
  onView,
  onApprove,
  onMerge,
  onMarkReady
}: PRRowProps) {
  const author = pr.author?.login ?? 'unknown'
  const isCopilot = author.toLowerCase().includes('copilot')

  // Strip [WIP] prefix from title
  let displayTitle = pr.title.replace(/^\[WIP\]\s*/i, '')
  if (displayTitle.length > 40) {
    displayTitle = displayTitle.substring(0, 40) + '...'
  }

  // Build status badges
  const badges: ReactElement[] = []
  if (pr.isDraft) {
    badges.push(
      <span key="draft" className="badge badge--warning">
        Draft
      </span>
    )
  }
  if (isCopilot && pr.copilotCompleted === false) {
    badges.push(
      <span key="wip" className="badge badge--info">
        WIP
      </span>
    )
  }

  // Review status badge
  const getReviewBadge = () => {
    if (pr.reviewDecision === 'APPROVED') {
      return <span className="badge badge--success">Approved</span>
    }
    if (pr.reviewDecision === 'CHANGES_REQUESTED') {
      return <span className="badge badge--danger">Changes</span>
    }
    return <span className="badge badge--secondary">Pending</span>
  }

  return (
    <tr>
      <td>
        <span className="repo-link">{pr.repo}</span>
        <span className="text-secondary">#{pr.number}</span>
      </td>
      <td>
        <a
          href={pr.url}
          target="_blank"
          rel="noopener noreferrer"
          className="pr-link"
          title={pr.title}
        >
          {escapeHtml(displayTitle)}
        </a>
        {badges.length > 0 && <span className="badge-group">{badges}</span>}
      </td>
      <td>
        <code className="branch-name" title={pr.headRefName}>
          {pr.headRefName}
        </code>
      </td>
      <td>
        {isCopilot ? '🤖' : '👤'}{' '}
        <span className="text-secondary">{author.replace('app/', '')}</span>
      </td>
      {showReviewStatus && <td>{getReviewBadge()}</td>}
      <td className="text-secondary">{formatTimeAgo(pr.createdAt)}</td>
      <td>
        <div className="pr-actions">
          <button className="btn btn--ghost btn--sm" onClick={onView} title="View Details">
            👁️
          </button>
          {isReady ? (
            <>
              <button className="btn btn--ghost btn--sm" onClick={onApprove} title="Approve">
                ✅
              </button>
              <button className="btn btn--ghost btn--sm" onClick={onMerge} title="Merge">
                🔀
              </button>
            </>
          ) : (
            <button
              className="btn btn--ghost btn--sm"
              onClick={onMarkReady}
              title="Mark Ready"
              disabled={!pr.isDraft}
            >
              ⏳
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
