/**
 * IssueDetail — per-issue view for the crimson-kitty pipeline.
 *
 * Sections:
 *   1. Header    — batch id, issue id, current state badge
 *   2. Timeline  — transitions.jsonl, newest first
 *   3. Gates     — gates.jsonl, one row per gate record
 *   4. Evidence  — per-gate `evidence_data` blobs rendered via EvidencePreview
 *   5. Events    — tail of events.jsonl
 */

import { useEffect } from 'react'
import { useTemporalStore } from '../../store/temporalStore'
import { StateBadge } from './StateBadge'
import { GateResultRow } from './GateResultRow'
import { EvidencePreview } from './EvidencePreview'

interface IssueDetailProps {
  batchId: string
  issueId: string
}

export function IssueDetail({ batchId, issueId }: IssueDetailProps) {
  const slot = useTemporalStore(s => s.issueDetail)
  const loadIssue = useTemporalStore(s => s.loadIssue)

  useEffect(() => {
    void loadIssue(batchId, issueId)
  }, [batchId, issueId, loadIssue])

  if (slot.loading && !slot.data) {
    return (
      <div className="temporal-issue-detail" data-testid="temporal-issue-detail-loading">
        Loading issue…
      </div>
    )
  }
  if (slot.error) {
    return (
      <div
        className="temporal-issue-detail temporal-issue-detail--error"
        data-testid="temporal-issue-detail-error"
      >
        {slot.error}
      </div>
    )
  }
  if (!slot.data) {
    return (
      <div className="temporal-issue-detail" data-testid="temporal-issue-detail-empty">
        (no issue selected)
      </div>
    )
  }

  const issue = slot.data
  const transitions = [...issue.transitions].reverse()

  return (
    <div className="temporal-issue-detail" data-testid="temporal-issue-detail">
      <header className="temporal-issue-detail__header">
        <h2 className="temporal-issue-detail__title">
          {issue.batch_id} / {issue.issue_id}
        </h2>
        <StateBadge state={issue.current_state} />
        {issue.is_deferred && (
          <span
            className="temporal-issue-detail__deferred-note"
            data-testid="temporal-issue-deferred-note"
          >
            deferred at {issue.deferred_at} via {issue.deferred_gate}
          </span>
        )}
      </header>

      <section className="temporal-issue-detail__section" data-testid="temporal-issue-timeline">
        <h3>Timeline ({issue.transitions.length})</h3>
        {transitions.length === 0 ? (
          <p>(no transitions)</p>
        ) : (
          <ol className="temporal-issue-detail__timeline">
            {transitions.map((t, i) => (
              <li key={`${t.ts}-${i}`} data-testid="temporal-transition">
                <span className="temporal-issue-detail__timeline-ts">{t.ts}</span>
                <span className="temporal-issue-detail__timeline-arrow">
                  {t.from} → {t.to}
                </span>
                <span className="temporal-issue-detail__timeline-reason">{t.reason}</span>
                <span className="temporal-issue-detail__timeline-by">by {t.decided_by}</span>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section className="temporal-issue-detail__section" data-testid="temporal-issue-gates">
        <h3>Gates ({issue.gates.length})</h3>
        {issue.gates.length === 0 ? (
          <p>(no gate records)</p>
        ) : (
          issue.gates.map((g, i) => <GateResultRow key={`${g.gate}-${i}`} record={g} />)
        )}
      </section>

      <section className="temporal-issue-detail__section" data-testid="temporal-issue-evidence">
        <h3>Evidence</h3>
        {issue.gates.filter(g => g.evidence_data).length === 0 ? (
          <p>(no evidence attached to gate records)</p>
        ) : (
          issue.gates
            .filter(g => g.evidence_data)
            .map((g, i) => (
              <EvidencePreview key={`${g.gate}-ev-${i}`} label={g.gate} value={g.evidence_data} />
            ))
        )}
      </section>

      <section className="temporal-issue-detail__section" data-testid="temporal-issue-events">
        <h3>Events ({issue.events.length})</h3>
        {issue.events.length === 0 ? (
          <p>(no events)</p>
        ) : (
          <ul className="temporal-issue-detail__events">
            {issue.events.slice(-20).map((e, i) => (
              <li key={i} data-testid="temporal-event">
                <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>
                  {JSON.stringify(e, null, 2)}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
