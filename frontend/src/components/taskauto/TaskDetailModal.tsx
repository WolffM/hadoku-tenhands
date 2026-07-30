/**
 * TaskDetailModal — one board task, end to end.
 *
 * A lane column can only afford a title, which is enough to see *where* a
 * task is and useless for asking *what happened to it*. That answer is spread
 * across three systems on purpose — the board holds the plan a human
 * approved, the claim log holds every turn an agent took, GitHub holds the
 * diff — and this is the one place they are shown together.
 *
 * The timeline interleaves all three by timestamp rather than listing them in
 * three sections. "Planned, asked a question, waited two days for an answer,
 * implemented, PR merged" is a sentence about elapsed time, and grouping by
 * source is what destroys it.
 */

import { useEffect } from 'react'
import { Badge, type BadgeVariant, LoadingState } from '../common'
import { formatDuration, formatTimeAgo, formatTimestamp, renderMarkdown } from '../../utils'
import type { TaskAutoTaskDetail, TaskAutoTaskPR } from '../../api/types'

interface TaskDetailModalProps {
  detail: TaskAutoTaskDetail | null
  loading: boolean
  error: string | null
  /** Title to show while the detail is still loading. */
  fallbackTitle: string
  onClose: () => void
}

const PR_VARIANT: Record<string, BadgeVariant> = {
  MERGED: 'success',
  OPEN: 'info',
  CLOSED: 'secondary'
}

/** One dot on the timeline. */
interface TimelineEvent {
  at: string
  label: string
  detail?: string
  variant: 'plan' | 'work' | 'pr' | 'merged' | 'board'
}

/**
 * An outcome string is `stage:result` — `plan:questions`, `pr-open:88`. Both
 * halves matter to a reader, so it is split rather than shown raw.
 */
function describeOutcome(outcome: string): { label: string; variant: TimelineEvent['variant'] } {
  if (!outcome) return { label: 'agent turn', variant: 'work' }
  const [stage, rest] = [outcome.split(':')[0], outcome.split(':').slice(1).join(':')]
  if (stage === 'plan') return { label: rest ? `planned — ${rest}` : 'planned', variant: 'plan' }
  if (stage === 'pr-open') return { label: `opened PR #${rest}`, variant: 'pr' }
  return { label: outcome, variant: 'work' }
}

function buildTimeline(detail: TaskAutoTaskDetail): TimelineEvent[] {
  const events: TimelineEvent[] = []

  if (detail.task.createdAt) {
    events.push({ at: detail.task.createdAt, label: 'task captured', variant: 'board' })
  }

  for (const claim of detail.history) {
    const { label, variant } = describeOutcome(claim.outcome)
    const started = new Date(claim.claimedAt).getTime()
    const ended = new Date(claim.endedAt).getTime()
    const held = isFinite(started) && isFinite(ended) ? (ended - started) / 1000 : null
    events.push({
      at: claim.claimedAt,
      label,
      detail: held === null ? claim.endedBy : `held ${formatDuration(held)} · ${claim.endedBy}`,
      variant
    })
  }

  for (const pr of detail.prs) {
    if (pr.mergedAt) {
      events.push({
        at: pr.mergedAt,
        label: `PR #${pr.number} merged`,
        detail: pr.branch,
        variant: 'merged'
      })
    } else if (pr.state === 'CLOSED') {
      events.push({
        at: pr.updatedAt,
        label: `PR #${pr.number} closed unmerged`,
        detail: pr.branch,
        variant: 'board'
      })
    }
  }

  return events.sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())
}

function PRCard({ pr }: { pr: TaskAutoTaskPR }) {
  return (
    <a
      className="taskauto-detail__pr"
      href={pr.url}
      target="_blank"
      rel="noreferrer"
      data-state={pr.state.toLowerCase()}
    >
      <div className="taskauto-detail__pr-head">
        <Badge variant={PR_VARIANT[pr.state] ?? 'secondary'}>{pr.state.toLowerCase()}</Badge>
        <span className="taskauto-detail__pr-title">
          #{pr.number} {pr.title}
        </span>
      </div>
      <div className="taskauto-detail__pr-meta">
        <span className="taskauto-pr__diff">
          +{pr.additions} / −{pr.deletions}
        </span>
        <span>
          {pr.changedFiles} file{pr.changedFiles === 1 ? '' : 's'}
        </span>
        {pr.state === 'OPEN' && <span>checks {pr.checks}</span>}
        <span>
          {pr.mergedAt ? `merged ${formatTimeAgo(pr.mergedAt)}` : formatTimeAgo(pr.updatedAt)}
        </span>
      </div>
    </a>
  )
}

export function TaskDetailModal({
  detail,
  loading,
  error,
  fallbackTitle,
  onClose
}: TaskDetailModalProps) {
  // Escape closes. A modal opened by clicking a lane card is a peek, and a
  // peek you can only leave with the mouse is an annoying one.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const metrics = detail?.task.metrics ?? {}
  const timeline = detail ? buildTimeline(detail) : []

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="taskauto-task-modal">
      <div className="modal taskauto-detail" onClick={e => e.stopPropagation()}>
        <div className="modal__header">
          <div className="modal__title-section">
            <h2 className="modal__title">{detail?.task.title ?? fallbackTitle}</h2>
            <span className="modal__subtitle">
              {detail ? `${detail.board.name} · ${detail.board.repo}` : 'Loading…'}
            </span>
          </div>
          <div className="modal__nav">
            <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
        </div>

        <div className="modal__content">
          {error && <p className="taskauto-error">{error}</p>}
          {loading && !detail && <LoadingState text="Loading task…" />}

          {detail && (
            <>
              <div className="taskauto-detail__facts">
                <Badge variant={detail.task.claimed ? 'info' : 'secondary'}>
                  {detail.task.lane}
                </Badge>
                {detail.task.claimed && <span className="taskauto-pulse" aria-hidden="true" />}
                <span>captured {formatTimeAgo(detail.task.createdAt)}</span>
                <span>touched {formatTimeAgo(detail.task.updatedAt)}</span>
                <code className="taskauto-pr__branch">{detail.task.branch}</code>
                {metrics.agent_s !== undefined && (
                  <span title="Agent seconds only — CI and human thinking time are not counted">
                    {formatDuration(metrics.agent_s)} of agent time
                  </span>
                )}
                {metrics.plan_passes !== undefined && (
                  <span>
                    {metrics.plan_passes} planning pass{metrics.plan_passes === 1 ? '' : 'es'}
                  </span>
                )}
              </div>

              {detail.prs.length > 0 && (
                <section className="taskauto-detail__section">
                  <h3 className="taskauto-detail__heading">Pull requests</h3>
                  {detail.prs.map(pr => (
                    <PRCard key={pr.number} pr={pr} />
                  ))}
                </section>
              )}

              <section className="taskauto-detail__section">
                <h3 className="taskauto-detail__heading">Timeline</h3>
                {timeline.length === 0 ? (
                  <p className="taskauto-detail__empty">No agent has picked this task up yet.</p>
                ) : (
                  <ol className="taskauto-timeline">
                    {timeline.map((e, i) => (
                      <li
                        key={`${e.at}-${i}`}
                        className="taskauto-timeline__item"
                        data-kind={e.variant}
                      >
                        <span className="taskauto-timeline__when" title={e.at}>
                          {formatTimestamp(e.at)}
                        </span>
                        <span className="taskauto-timeline__label">{e.label}</span>
                        {e.detail && <span className="taskauto-timeline__detail">{e.detail}</span>}
                      </li>
                    ))}
                  </ol>
                )}
              </section>

              <section className="taskauto-detail__section">
                <h3 className="taskauto-detail__heading">Plan</h3>
                {detail.task.notes ? (
                  <div
                    className="taskauto-detail__notes markdown-content"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.task.notes) }}
                  />
                ) : (
                  <p className="taskauto-detail__empty">
                    Nothing written yet — this task hasn&apos;t been planned.
                  </p>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
