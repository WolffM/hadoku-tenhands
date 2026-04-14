/**
 * PipelineInbox — operator inbox for deferred crimson-kitty workflows.
 *
 * Each row corresponds to one `awaiting/inbox_entry.json`. The operator
 * resolves a deferred workflow with approve / abort / retry. Clicking a
 * button POSTs to `/api/temporal/issue/<workflow_id>/signal`; on success
 * the row is optimistically removed. On failure the inbox is re-fetched.
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

function InboxRow({ item, onSignal, pending }: RowProps) {
  const workflowId = workflowIdFor(item)
  const isPending = pending === workflowId

  return (
    <li
      className="temporal-inbox__row"
      data-testid="temporal-inbox-row"
      data-workflow-id={workflowId}
    >
      <div className="temporal-inbox__meta">
        <span className="temporal-inbox__batch">{item.batch_id}</span>
        <span className="temporal-inbox__issue">{item.issue_id}</span>
        {item.state && <span className="temporal-inbox__state">state: {item.state}</span>}
        {item.gate && <span className="temporal-inbox__gate">gate: {item.gate}</span>}
        {item.reason && <span className="temporal-inbox__reason">{item.reason}</span>}
        {item.queued_at && <span className="temporal-inbox__queued">{item.queued_at}</span>}
      </div>
      <div className="temporal-inbox__actions">
        <button
          type="button"
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
