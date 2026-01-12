/**
 * DiffViewer Component
 *
 * Displays git diff with syntax highlighting.
 */

import { useMemo } from 'react'
import DOMPurify from 'dompurify'
import { renderDiffToHtml, getDiffStats } from '../../utils'

interface DiffViewerProps {
  diff: string
  showStats?: boolean
}

export function DiffViewer({ diff, showStats = true }: DiffViewerProps) {
  const diffHtml = useMemo(() => renderDiffToHtml(diff), [diff])
  const sanitizedHtml = useMemo(() => DOMPurify.sanitize(diffHtml), [diffHtml])
  const stats = useMemo(() => (showStats ? getDiffStats(diff) : null), [diff, showStats])

  if (!diff || diff.trim() === '') {
    return (
      <div className="diff-viewer diff-viewer-empty">
        <p>No changes to display</p>
      </div>
    )
  }

  return (
    <div className="diff-viewer">
      {stats && (
        <div className="diff-viewer-stats">
          <span className="stat-files">{stats.files} files changed</span>
          <span className="stat-additions">+{stats.additions}</span>
          <span className="stat-deletions">-{stats.deletions}</span>
        </div>
      )}
      <div className="diff-viewer-content" dangerouslySetInnerHTML={{ __html: sanitizedHtml }} />
    </div>
  )
}
