/**
 * PipelineInbox — operator inbox for deferred crimson-kitty workflows.
 *
 * Each row corresponds to one `awaiting/inbox_entry.json`. The operator
 * resolves a deferred workflow with approve / abort / retry. Clicking a
 * button POSTs to `/api/temporal/issue/<workflow_id>/signal`; on success
 * the row is optimistically removed. On failure the inbox is re-fetched.
 *
 * Phase 5.4 — the row layout branches on `gate_name`:
 *   - operator_signoff → signoff card (Phase 4.5+ flow): preview PR
 *     URL is the primary call-to-action, body excerpt rendered inline,
 *     Approve & Ship Upstream / Abort buttons.
 *   - relevance / submission_judge / anything else → judge-defer card:
 *     score, reason, evidence-file links, Approve / Abort / Retry.
 *
 * Falls back to a `batch_id-issue_id` workflow id when the inbox entry
 * does not include an explicit `workflow_id` — this mirrors how the
 * dispatch endpoint constructs workflow ids today.
 */

import { useEffect, useState } from 'react'
import { useTemporalStore } from '../../store/temporalStore'
import type { TemporalInboxItem, TemporalSignalDecision } from '../../api/types'

function workflowIdFor(item: TemporalInboxItem): string {
  if (typeof item.workflow_id === 'string' && item.workflow_id) return item.workflow_id
  return `issue-${item.batch_id}-${item.issue_id}`
}

interface RowProps {
  item: TemporalInboxItem
  onSignal: (workflowId: string, decision: TemporalSignalDecision) => Promise<void>
  pending: string | null
}

function SignoffCard({ item, onSignal, pending }: RowProps) {
  const workflowId = workflowIdFor(item)
  const isPending = pending === workflowId
  const previewUrl = item.operator_pr_url
  const excerpt = item.pr_body_excerpt ?? ''

  return (
    <li
      className="temporal-inbox__row temporal-inbox__row--signoff"
      data-testid="temporal-inbox-row"
      data-card-variant="signoff"
      data-workflow-id={workflowId}
    >
      <div className="temporal-inbox__signoff-header">
        <div className="temporal-inbox__signoff-title">
          <span className="temporal-inbox__batch">{item.batch_id}</span>
          <span className="temporal-inbox__issue">{item.issue_id}</span>
        </div>
        {item.pr_title && (
          <div className="temporal-inbox__pr-title" data-testid="temporal-inbox-pr-title">
            {item.pr_title}
          </div>
        )}
      </div>

      {previewUrl && (
        <a
          className="btn btn--primary temporal-inbox__preview-link"
          href={previewUrl}
          target="_blank"
          rel="noopener noreferrer"
          data-testid="temporal-inbox-preview-link"
        >
          Review on GitHub →
        </a>
      )}

      {excerpt && (
        <pre
          className="temporal-inbox__pr-body-excerpt"
          data-testid="temporal-inbox-pr-body-excerpt"
        >
          {excerpt}
        </pre>
      )}

      <p className="temporal-inbox__signoff-note">
        Edits to the fork preview PR are picked up live when you approve. The pipeline re-runs the
        sanitizer on the live content.
      </p>

      <div className="temporal-inbox__actions">
        <button
          type="button"
          className="btn btn--success"
          data-testid="temporal-inbox-approve"
          disabled={isPending}
          onClick={() => {
            void onSignal(workflowId, 'approve')
          }}
        >
          Approve & ship upstream
        </button>
        <button
          type="button"
          className="btn btn--danger"
          data-testid="temporal-inbox-abort"
          disabled={isPending}
          onClick={() => {
            void onSignal(workflowId, 'abort')
          }}
        >
          Abort
        </button>
      </div>
    </li>
  )
}

function JudgeDeferCard({ item, onSignal, pending }: RowProps) {
  const workflowId = workflowIdFor(item)
  const isPending = pending === workflowId

  return (
    <li
      className="temporal-inbox__row"
      data-testid="temporal-inbox-row"
      data-card-variant="judge-defer"
      data-workflow-id={workflowId}
    >
      <div className="temporal-inbox__meta">
        <span className="temporal-inbox__batch">{item.batch_id}</span>
        <span className="temporal-inbox__issue">{item.issue_id}</span>
        {item.state && <span className="temporal-inbox__state">state: {item.state}</span>}
        {item.gate && <span className="temporal-inbox__gate">gate: {item.gate}</span>}
        {typeof item.score === 'number' && (
          <span className="temporal-inbox__score" data-testid="temporal-inbox-score">
            score: {item.score.toFixed(2)}
          </span>
        )}
        {item.reason && <span className="temporal-inbox__reason">{item.reason}</span>}
        {item.queued_at && <span className="temporal-inbox__queued">{item.queued_at}</span>}
      </div>
      <div className="temporal-inbox__actions">
        <button
          type="button"
          className="btn btn--success btn--sm"
          data-testid="temporal-inbox-approve"
          disabled={isPending}
          onClick={() => {
            void onSignal(workflowId, 'approve')
          }}
        >
          Approve
        </button>
        <button
          type="button"
          className="btn btn--danger btn--sm"
          data-testid="temporal-inbox-abort"
          disabled={isPending}
          onClick={() => {
            void onSignal(workflowId, 'abort')
          }}
        >
          Abort
        </button>
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          data-testid="temporal-inbox-retry"
          disabled={isPending}
          onClick={() => {
            void onSignal(workflowId, 'retry')
          }}
        >
          Retry
        </button>
      </div>
    </li>
  )
}

function InboxRow(props: RowProps) {
  if (props.item.gate === 'operator_signoff') {
    return <SignoffCard {...props} />
  }
  return <JudgeDeferCard {...props} />
}

export function PipelineInbox() {
  const inbox = useTemporalStore(s => s.inbox)
  const loadInbox = useTemporalStore(s => s.loadInbox)
  const sendSignal = useTemporalStore(s => s.sendSignal)
  const [pending, setPending] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)

  useEffect(() => {
    void loadInbox()
  }, [loadInbox])

  const handleSignal = async (workflowId: string, decision: TemporalSignalDecision) => {
    setPending(workflowId)
    setLastError(null)
    try {
      await sendSignal(workflowId, decision)
    } catch (err) {
      setLastError(err instanceof Error ? err.message : String(err))
      // Re-fetch so UI reflects server truth after a failed optimistic update.
      void loadInbox()
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="temporal-inbox" data-testid="temporal-inbox">
      <header className="temporal-inbox__header">
        <h2>Pipeline Inbox</h2>
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={() => {
            void loadInbox()
          }}
          disabled={inbox.loading}
        >
          Refresh
        </button>
      </header>
      {inbox.error && (
        <div className="temporal-inbox__error" data-testid="temporal-inbox-error">
          {inbox.error}
        </div>
      )}
      {lastError && (
        <div className="temporal-inbox__error" data-testid="temporal-inbox-signal-error">
          {lastError}
        </div>
      )}
      {inbox.loading && inbox.items.length === 0 ? (
        <p data-testid="temporal-inbox-loading">Loading inbox…</p>
      ) : inbox.items.length === 0 ? (
        <p data-testid="temporal-inbox-empty">Inbox is empty.</p>
      ) : (
        <ul className="temporal-inbox__list">
          {inbox.items.map(item => (
            <InboxRow
              key={`${item.batch_id}-${item.issue_id}`}
              item={item}
              onSignal={handleSignal}
              pending={pending}
            />
          ))}
        </ul>
      )}
    </div>
  )
}
