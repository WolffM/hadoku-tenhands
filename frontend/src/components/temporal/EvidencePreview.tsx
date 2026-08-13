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
 *   - string that looks like a unified diff → the shared DiffViewer
 *   - plain string → <pre>
 *   - { kind: 'image', src } → <img>
 *
 * A future backend endpoint can feed real file contents through the same
 * component without changing the render path.
 */

import type { ReactElement } from 'react'
import { DiffViewer } from '../review'

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

function renderJson(value: unknown): ReactElement {
  return (
    <pre className="temporal-evidence__json" data-testid="temporal-evidence-json">
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
      body = (
        <div className="temporal-evidence__diff" data-testid="temporal-evidence-diff">
          <DiffViewer diff={value} />
        </div>
      )
    } else {
      body = (
        <pre className="temporal-evidence__text" data-testid="temporal-evidence-text">
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
          className="temporal-evidence__image"
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
