/**
 * EvidencePreview — renders one piece of evidence inline.
 *
 * Backend routes are locked for Phase 2, and the existing `/issue/...`
 * endpoint returns JSONL transitions/gates/events but does not stream raw
 * evidence files (per operator decision: ship 2.4 against `evidence_data`
 * only — option (a)). This component therefore renders structured data
 * that IS already available on the wire:
 *
 *   - JSON / object → pretty-printed JSON
 *   - string that looks like a unified diff → minimal hand-rolled diff renderer
 *   - plain string → <pre>
 *   - { kind: 'image', src } → <img>
 *
 * A future backend endpoint can feed real file contents through the same
 * component without changing the render path.
 */

import type { CSSProperties, ReactElement } from 'react'

export type EvidenceValue =
  | null
  | undefined
  | string
  | number
  | boolean
  | { kind: 'image'; src: string; alt?: string }
  | Record<string, unknown>
  | unknown[]

interface EvidencePreviewProps {
  value: EvidenceValue
  label?: string
}

function looksLikeDiff(text: string): boolean {
  // minimal heuristic — a unified diff has either `diff --git` or at least
  // one hunk header line (`@@ ... @@`) plus +/- line markers.
  if (text.includes('diff --git')) return true
  if (/^@@ .+ @@/m.test(text) && /^[+-]/m.test(text)) return true
  return false
}

function renderDiff(text: string): ReactElement {
  const lines = text.split('\n')
  return (
    <pre
      className="temporal-evidence__diff"
      data-testid="temporal-evidence-diff"
      style={diffContainerStyle}
    >
      {lines.map((line, i) => {
        const style = lineStyle(line)
        return (
          <span key={i} style={style}>
            {line || ' '}
            {'\n'}
          </span>
        )
      })}
    </pre>
  )
}

const diffContainerStyle: CSSProperties = {
  fontFamily: 'monospace',
  fontSize: 'var(--hdk-text-xs)',
  whiteSpace: 'pre',
  overflowX: 'auto',
  padding: 'var(--hdk-space-sm)',
  background: 'var(--color-bg-alt)',
  borderRadius: 'var(--hdk-radius-sm)'
}

function lineStyle(line: string): CSSProperties {
  if (line.startsWith('+++') || line.startsWith('---')) {
    return { color: 'var(--color-text-muted)', fontWeight: 'bold' }
  }
  if (line.startsWith('@@')) {
    return { color: 'var(--color-primary)' }
  }
  if (line.startsWith('+')) {
    return { color: 'var(--color-success)' }
  }
  if (line.startsWith('-')) {
    return { color: 'var(--color-danger)' }
  }
  return {}
}

function renderJson(value: unknown): ReactElement {
  return (
    <pre
      className="temporal-evidence__json"
      data-testid="temporal-evidence-json"
      style={{ fontFamily: 'monospace', fontSize: '12px', whiteSpace: 'pre-wrap' }}
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function EvidencePreview({ value, label }: EvidencePreviewProps) {
  let body: ReactElement

  if (value === null || value === undefined) {
    body = (
      <span data-testid="temporal-evidence-empty" className="temporal-evidence__empty">
        (no evidence)
      </span>
    )
  } else if (typeof value === 'string') {
    if (looksLikeDiff(value)) {
      body = renderDiff(value)
    } else {
      body = (
        <pre
          className="temporal-evidence__text"
          data-testid="temporal-evidence-text"
          style={{ whiteSpace: 'pre-wrap' }}
        >
          {value}
        </pre>
      )
    }
  } else if (typeof value === 'object' && value !== null && 'kind' in value) {
    const v = value as { kind: string; src?: string; alt?: string }
    if (v.kind === 'image' && v.src) {
      body = (
        <img
          src={v.src}
          alt={v.alt || label || 'evidence'}
          data-testid="temporal-evidence-image"
          style={{ maxWidth: '100%', borderRadius: '4px' }}
        />
      )
    } else {
      body = renderJson(value)
    }
  } else {
    body = renderJson(value)
  }

  return (
    <div className="temporal-evidence" data-testid="temporal-evidence">
      {label && <div className="temporal-evidence__label">{label}</div>}
      {body}
    </div>
  )
}
