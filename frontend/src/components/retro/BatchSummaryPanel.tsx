/**
 * BatchSummaryPanel — funnel visualization for a batch.
 *
 * Dispatched → Fork PRs → Upstream PRs → [Merged | Closed | Open]
 */

import type { BatchSummary } from '../../api/types'

interface Props {
  batch: BatchSummary
}

export function BatchSummaryPanel({ batch }: Props) {
  const stages = [
    { label: 'Dispatched', count: batch.issue_count, variant: 'neutral' },
    { label: 'Upstream PRs', count: batch.upstream_pr_count, variant: 'neutral' }
  ]

  const outcomes = [
    { label: 'Merged', count: batch.upstream_merged, variant: 'success' },
    { label: 'Closed', count: batch.upstream_closed, variant: 'closed' },
    { label: 'Open', count: batch.upstream_open, variant: 'open' }
  ]

  return (
    <div className="batch-summary">
      <div className="batch-summary__title">
        <span className="batch-summary__id">{batch.batch_id}</span>
        {batch.note && <span className="batch-summary__note">{batch.note}</span>}
      </div>
      <div className="batch-summary__funnel">
        {stages.map((s, i) => (
          <div key={s.label} className="batch-summary__funnel-row">
            <div className={`batch-summary__stage batch-summary__stage--${s.variant}`}>
              <span className="batch-summary__count">{s.count}</span>
              <span className="batch-summary__label">{s.label}</span>
            </div>
            {i < stages.length - 1 && <span className="batch-summary__arrow">→</span>}
          </div>
        ))}
        <span className="batch-summary__arrow">→</span>
        <div className="batch-summary__outcomes">
          {outcomes.map(o => (
            <div
              key={o.label}
              className={`batch-summary__outcome batch-summary__outcome--${o.variant}`}
            >
              <span className="batch-summary__count">{o.count}</span>
              <span className="batch-summary__label">{o.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
