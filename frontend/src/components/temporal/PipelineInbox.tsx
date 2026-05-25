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
import type { TemporalInboxItem, TemporalSignalDecision, TemporalReasonCode } from '../../api/types'

function workflowIdFor(item: TemporalInboxItem): string {
  if (typeof item.workflow_id === 'string' && item.workflow_id) return item.workflow_id
  // Mirrors batch_workflow.py:47 — `{batch_id}-{issue_id}`, no `issue-` prefix.
  return `${item.batch_id}-${item.issue_id}`
}

// Reason codes per decision — mirrors backend _OVERRIDE_REASON_CODES.
// Phase 0 / M0.2: structured operator override capture for the
// calibration corpus.
const REASON_CODES: Record<TemporalSignalDecision, { code: TemporalReasonCode; label: string }[]> =
  {
    approve: [
      { code: 'approve_clean', label: 'Approve — preview looks good as-is' },
      { code: 'approve_after_edit', label: 'Approve — after editing the preview PR' }
    ],
    abort: [
      {
        code: 'abort_scope_mismatch',
        label: "Abort — issue scope doesn't match what we worked on"
      },
      { code: 'abort_quality', label: 'Abort — fix is wrong / partial / unsafe' },
      { code: 'abort_active_upstream', label: 'Abort — someone else already has a PR' },
      { code: 'abort_stale_issue', label: 'Abort — issue is dead / wrong version / closed' },
      { code: 'abort_other', label: 'Abort — other (free-text required)' }
    ],
    retry: [
      { code: 'retry_transient', label: 'Retry — transient failure' },
      { code: 'retry_with_changes', label: 'Retry — after manual changes' }
    ]
  }

type SignalHandler = (
  workflowId: string,
  decision: TemporalSignalDecision,
  options: { reasonCode: TemporalReasonCode; reasonText: string }
) => Promise<void>

interface RowProps {
  item: TemporalInboxItem
  onSignal: SignalHandler
  pending: string | null
}

interface ReasonPickerProps {
  decision: TemporalSignalDecision
  disabled: boolean
  onConfirm: (reasonCode: TemporalReasonCode, reasonText: string) => void
  onCancel: () => void
}

function ReasonPicker({ decision, disabled, onConfirm, onCancel }: ReasonPickerProps) {
  const options = REASON_CODES[decision]
  const [code, setCode] = useState<TemporalReasonCode>(options[0].code)
  const [text, setText] = useState('')
  const requiresText = code === 'abort_other'
  const canConfirm = !disabled && (!requiresText || text.trim().length > 0)

  return (
    <div className="temporal-inbox__reason-picker" data-testid="temporal-inbox-reason-picker">
      <label className="temporal-inbox__reason-label">
        Reason
        <select
          data-testid="temporal-inbox-reason-select"
          value={code}
          disabled={disabled}
          onChange={e => setCode(e.target.value as TemporalReasonCode)}
        >
          {options.map(opt => (
            <option key={opt.code} value={opt.code}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>
      <textarea
        data-testid="temporal-inbox-reason-text"
        className="temporal-inbox__reason-text"
        placeholder={requiresText ? 'Required: what was wrong?' : 'Optional context'}
        value={text}
        disabled={disabled}
        onChange={e => setText(e.target.value)}
        rows={2}
      />
      <div className="temporal-inbox__reason-actions">
        <button
          type="button"
          className="btn btn--primary btn--sm"
          data-testid="temporal-inbox-reason-confirm"
          disabled={!canConfirm}
          onClick={() => onConfirm(code, text.trim())}
        >
          Confirm {decision}
        </button>
        <button
          type="button"
          className="btn btn--secondary btn--sm"
          data-testid="temporal-inbox-reason-cancel"
          disabled={disabled}
          onClick={onCancel}
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function SignoffCard({ item, onSignal, pending }: RowProps) {
  const workflowId = workflowIdFor(item)
  const isPending = pending === workflowId
  const previewUrl = item.operator_pr_url
  const excerpt = item.pr_body_excerpt ?? ''
  const [chosenDecision, setChosenDecision] = useState<TemporalSignalDecision | null>(null)

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

      {chosenDecision === null ? (
        <div className="temporal-inbox__actions">
          <button
            type="button"
            className="btn btn--success"
            data-testid="temporal-inbox-approve"
            disabled={isPending}
            onClick={() => setChosenDecision('approve')}
          >
            Approve & ship upstream
          </button>
          <button
            type="button"
            className="btn btn--danger"
            data-testid="temporal-inbox-abort"
            disabled={isPending}
            onClick={() => setChosenDecision('abort')}
          >
            Abort
          </button>
        </div>
      ) : (
        <ReasonPicker
          decision={chosenDecision}
          disabled={isPending}
          onConfirm={(reasonCode, reasonText) => {
            void onSignal(workflowId, chosenDecision, { reasonCode, reasonText })
            setChosenDecision(null)
          }}
          onCancel={() => setChosenDecision(null)}
        />
      )}
    </li>
  )
}

function JudgeDeferCard({ item, onSignal, pending }: RowProps) {
  const workflowId = workflowIdFor(item)
  const isPending = pending === workflowId
  const [chosenDecision, setChosenDecision] = useState<TemporalSignalDecision | null>(null)

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
      {chosenDecision === null ? (
        <div className="temporal-inbox__actions">
          <button
            type="button"
            className="btn btn--success btn--sm"
            data-testid="temporal-inbox-approve"
            disabled={isPending}
            onClick={() => setChosenDecision('approve')}
          >
            Approve
          </button>
          <button
            type="button"
            className="btn btn--danger btn--sm"
            data-testid="temporal-inbox-abort"
            disabled={isPending}
            onClick={() => setChosenDecision('abort')}
          >
            Abort
          </button>
          <button
            type="button"
            className="btn btn--secondary btn--sm"
            data-testid="temporal-inbox-retry"
            disabled={isPending}
            onClick={() => setChosenDecision('retry')}
          >
            Retry
          </button>
        </div>
      ) : (
        <ReasonPicker
          decision={chosenDecision}
          disabled={isPending}
          onConfirm={(reasonCode, reasonText) => {
            void onSignal(workflowId, chosenDecision, { reasonCode, reasonText })
            setChosenDecision(null)
          }}
          onCancel={() => setChosenDecision(null)}
        />
      )}
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

  const handleSignal: SignalHandler = async (workflowId, decision, options) => {
    setPending(workflowId)
    setLastError(null)
    try {
      await sendSignal(workflowId, decision, options)
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
