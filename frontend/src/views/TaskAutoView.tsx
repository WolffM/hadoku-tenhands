/**
 * TaskAutoView
 *
 * Status page for hadoku-task-automation: what is running, what is sitting in
 * which lane on which board, and the pull requests waiting on a human.
 *
 * The pipeline ends at "PR open" and hands off to GitHub. This is the missing
 * half — and the reason it belongs here rather than being a nicer GitHub
 * client is the pairing: a PR is shown next to the task it came from, so the
 * plan you approved sits beside the diff it produced. GitHub cannot show that.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { getTaskAutoStatus, mergeTaskAutoPR } from '../api'
import type { TaskAutoBoard, TaskAutoPR, TaskAutoStatus } from '../api/types'
import { EmptyState, LoadingState, SectionHeader } from '../components/common'

/** Lanes a human is expected to act on, so they can be pulled to the front. */
const HUMAN_LANES = new Set(['plan-review', 'replan', 'approved', 'stalled'])

function laneClass(lane: string): string {
  if (lane === 'stalled') return 'taskauto-lane--stalled'
  if (HUMAN_LANES.has(lane)) return 'taskauto-lane--human'
  if (lane === '(inbox)') return 'taskauto-lane--inbox'
  return 'taskauto-lane--agent'
}

function PRCard({
  pr,
  taskTitle,
  busy,
  onMerge
}: {
  pr: TaskAutoPR
  taskTitle?: string
  busy: boolean
  onMerge: () => void
}) {
  // Merge is offered only when GitHub says it would succeed. A button that
  // reliably fails teaches people to ignore buttons.
  const mergeable = pr.mergeState === 'CLEAN' && pr.checks !== 'failing' && !pr.isDraft
  return (
    <div className="taskauto-pr">
      <div className="taskauto-pr__head">
        <a className="taskauto-pr__title" href={pr.url} target="_blank" rel="noreferrer">
          {pr.repo.split('/')[1]} #{pr.number} — {pr.title}
        </a>
        <span className={`taskauto-pr__checks taskauto-pr__checks--${pr.checks}`}>
          {pr.checks}
        </span>
      </div>
      {taskTitle && (
        <div className="taskauto-pr__task" title="the task this PR came from">
          from: {taskTitle}
        </div>
      )}
      <div className="taskauto-pr__meta">
        <span className="taskauto-pr__diff">
          +{pr.additions}/-{pr.deletions}
        </span>
        <span>
          {pr.changedFiles} file{pr.changedFiles === 1 ? '' : 's'}
        </span>
        <span className="taskauto-pr__state">{pr.mergeState.toLowerCase()}</span>
        {pr.isDraft && <span className="taskauto-pr__state">draft</span>}
      </div>
      <div className="taskauto-pr__actions">
        <a className="btn btn--secondary btn--sm" href={pr.url} target="_blank" rel="noreferrer">
          Review diff
        </a>
        <button
          className="btn btn--primary btn--sm"
          disabled={!mergeable || busy}
          onClick={onMerge}
          title={mergeable ? 'Squash and merge' : `not mergeable (${pr.mergeState})`}
        >
          {busy ? 'Merging…' : 'Merge'}
        </button>
      </div>
    </div>
  )
}

function BoardCard({
  board,
  laneOrder,
  busyPR,
  onMerge
}: {
  board: TaskAutoBoard
  laneOrder: string[]
  busyPR: string | null
  onMerge: (pr: TaskAutoPR) => void
}) {
  const titleFor = useMemo(() => {
    const map = new Map<string, string>()
    for (const lane of Object.values(board.lanes ?? {})) {
      for (const t of lane) map.set(t.id.toLowerCase(), t.title)
    }
    return map
  }, [board.lanes])

  const total = Object.values(board.counts ?? {}).reduce((n, c) => n + c, 0)

  return (
    <div className="taskauto-board">
      <div className="taskauto-board__head">
        <h3 className="taskauto-board__name">{board.name}</h3>
        <span className="taskauto-board__repo">{board.repo}</span>
        <span className="taskauto-board__total">
          {total} task{total === 1 ? '' : 's'}
        </span>
      </div>

      {board.error ? (
        <div className="taskauto-board__error">{board.error}</div>
      ) : (
        <div className="taskauto-lanes">
          {laneOrder
            .filter(lane => (board.counts?.[lane] ?? 0) > 0)
            .map(lane => (
              <div key={lane} className={`taskauto-lane ${laneClass(lane)}`}>
                <div className="taskauto-lane__head">
                  <span className="taskauto-lane__name">{lane}</span>
                  <span className="taskauto-lane__count">{board.counts[lane]}</span>
                </div>
                <ul className="taskauto-lane__tasks">
                  {(board.lanes[lane] ?? []).map(t => (
                    <li key={t.id} className="taskauto-task" title={t.title}>
                      {t.claimed && <span className="taskauto-task__dot" title="claimed — running now" />}
                      {t.stuck && (
                        <span className="taskauto-task__stuck" title="two lane tags — invisible to the scheduler">
                          !
                        </span>
                      )}
                      <span className="taskauto-task__title">{t.title}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
        </div>
      )}

      {board.prs.length > 0 && (
        <div className="taskauto-board__prs">
          {board.prs.map(pr => (
            <PRCard
              key={`${pr.repo}#${pr.number}`}
              pr={pr}
              taskTitle={titleFor.get((pr.taskId || '').toLowerCase())}
              busy={busyPR === `${pr.repo}#${pr.number}`}
              onMerge={() => onMerge(pr)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function TaskAutoView() {
  const [status, setStatus] = useState<TaskAutoStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyPR, setBusyPR] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await getTaskAutoStatus()
      setStatus(data)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    // A run takes minutes and the cron is every 15, so a slow poll is plenty;
    // anything faster just spends gh calls to watch nothing change.
    const id = setInterval(() => void load(), 60_000)
    return () => clearInterval(id)
  }, [load])

  const onMerge = useCallback(
    async (pr: TaskAutoPR) => {
      const key = `${pr.repo}#${pr.number}`
      setBusyPR(key)
      try {
        await mergeTaskAutoPR(pr.repo, pr.number)
        await load()
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setBusyPR(null)
      }
    },
    [load]
  )

  if (loading && !status) return <LoadingState text="Reading the boards…" />

  const running = status?.running ?? []

  return (
    <div className="taskauto-view">
      <SectionHeader icon={'\u{1F4CB}'} title="Task Automation" count={status?.prCount} />

      {error && <div className="taskauto-error">{error}</div>}

      <div className="taskauto-summary">
        <div className="taskauto-summary__stat">
          <span className="taskauto-summary__num">{running.length}</span>
          <span className="taskauto-summary__label">running now</span>
        </div>
        <div className="taskauto-summary__stat">
          <span className="taskauto-summary__num">{status?.prCount ?? 0}</span>
          <span className="taskauto-summary__label">PRs awaiting you</span>
        </div>
        <div className="taskauto-summary__stat">
          <span className="taskauto-summary__num">{status?.boards.length ?? 0}</span>
          <span className="taskauto-summary__label">boards</span>
        </div>
      </div>

      {running.length > 0 && (
        <div className="taskauto-running">
          {running.map(t => (
            <div key={t.id} className="taskauto-running__item">
              <span className="taskauto-task__dot" />
              <span className="taskauto-running__lane">{t.lane}</span>
              <span className="taskauto-running__board">{t.board}</span>
              <span className="taskauto-running__title">{t.title}</span>
            </div>
          ))}
        </div>
      )}

      {status && status.boards.length === 0 && (
        <EmptyState
          icon={'\u{1F4CB}'}
          title="No automation boards"
          description="Nothing is shared with this key at contributor."
        />
      )}

      <div className="taskauto-boards">
        {status?.boards.map(b => (
          <BoardCard
            key={b.handle}
            board={b}
            laneOrder={status.laneOrder}
            busyPR={busyPR}
            onMerge={onMerge}
          />
        ))}
      </div>
    </div>
  )
}
