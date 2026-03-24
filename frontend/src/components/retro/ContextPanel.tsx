/**
 * ContextPanel — slide-in right panel for displaying context.md or upstream PR body.
 */

import { useEffect } from 'react'
import { renderMarkdown } from '../../utils'

interface Props {
  title: string
  body: string
  onClose: () => void
}

export function ContextPanel({ title, body, onClose }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <>
      <div className="context-panel-overlay" onClick={onClose} />
      <div className="context-panel">
        <div className="context-panel__header">
          <span className="context-panel__title">{title}</span>
          <button className="context-panel__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div
          className="context-panel__body markdown-body"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(body) }}
        />
      </div>
    </>
  )
}
