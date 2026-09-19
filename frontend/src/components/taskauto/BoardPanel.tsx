/**
 * BoardPanel — one automation board as a row of lanes.
 *
 * **A lane is a repo** since autoland v3, so the columns are the repos the
 * board covers and the pipeline's state lives on each card's chip instead.
 * That is why nothing here switches on a lane NAME any more: v2 could colour
 * `stalled` red because the vocabulary was fixed, and a repo list is not.
 *
 * Lanes render in the board's own order (each board sends its own
 * `laneOrder`), so adding a repo shows up without a frontend change — which
 * matters more now, because adding a repo no longer needs a deploy at all.
 *
 * A task carrying two lane tags resolves to no lane at all, which makes it
 * invisible to the scheduler — it sits there looking fine and is never picked
 * up. That failure has happened twice in production, so it gets a loud marker
 * rather than being folded into a count.
 */

import { Badge, type BadgeVariant } from '../common'
import type { TaskAutoBoard, TaskAutoStatusKind, TaskAutoTask } from '../../api/types'

/** The chip's four states. `waiting` is the one that wants a person. */
const CHIP_VARIANT: Record<TaskAutoStatusKind, BadgeVariant> = {
  working: 'info',
  waiting: 'warning',
  blocked: 'danger',
  done: 'success'
}

function TaskChip({ task }: { task: TaskAutoTask }) {
  if (!task.status) return null
  const { kind, label, href } = task.status
  const badge = <Badge variant={CHIP_VARIANT[kind] ?? 'secondary'}>{label}</Badge>
  // The href is nearly always the pull request. Stop the click reaching the
  // row's button, which opens the task detail instead of the PR.
  return href ? (
    <a
      className="taskauto-lane__chip"
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={e => e.stopPropagation()}
    >
      {badge}
    </a>
  ) : (
    <span className="taskauto-lane__chip">{badge}</span>
  )
}

interface BoardPanelProps {
  board: TaskAutoBoard
  laneOrder: string[]
  /** Open one task's full history. */
  onOpenTask: (board: string, taskId: string) => void
}

export function BoardPanel({ board, laneOrder, onOpenTask }: BoardPanelProps) {
  const total = Object.values(board.lanes).reduce((n, tasks) => n + tasks.length, 0)
  // Each board declares its own repos; the prop is the union across boards and
  // is only the fallback for a board read that failed before it could say.
  const order = board.laneOrder?.length ? board.laneOrder : laneOrder

  return (
    <section className="taskauto-board" data-testid={`taskauto-board-${board.handle}`}>
      <header className="taskauto-board__head">
        <h3 className="taskauto-board__name">{board.name}</h3>
        <code className="taskauto-board__repo">
          {Object.keys(board.laneRepos ?? {}).length || board.repo
            ? `${Object.keys(board.laneRepos ?? {}).length || 1} repo${
                Object.keys(board.laneRepos ?? {}).length === 1 ? '' : 's'
              }`
            : board.repo}
        </code>
        <span className="taskauto-board__total">
          {total} task{total === 1 ? '' : 's'}
        </span>
      </header>

      {board.error ? (
        <p className="taskauto-board__error">{board.error}</p>
      ) : (
        <div className="taskauto-lanes">
          {order.map(lane => {
            const tasks = board.lanes[lane] ?? []
            if (tasks.length === 0) return null
            return (
              <div key={lane} className="taskauto-lane">
                <div className="taskauto-lane__head">
                  <Badge variant={lane === '(inbox)' ? 'secondary' : 'info'}>{lane}</Badge>
                  {board.laneRepos?.[lane] && (
                    <code className="taskauto-lane__repo">{board.laneRepos[lane]}</code>
                  )}
                  <span className="taskauto-lane__count">{tasks.length}</span>
                </div>
                <ul className="taskauto-lane__tasks">
                  {tasks.map(t => (
                    <li key={t.id} className="taskauto-lane__task" data-stuck={t.stuck}>
                      <button
                        type="button"
                        className="taskauto-lane__task-btn"
                        title={t.title}
                        data-testid={`taskauto-task-${t.id}`}
                        onClick={() => onOpenTask(board.handle, t.id)}
                      >
                        {t.claimed && <span className="taskauto-pulse" aria-hidden="true" />}
                        <span className="taskauto-lane__task-title">{t.title}</span>
                        <TaskChip task={t} />
                        {t.needsApproval ? (
                          <span
                            className="taskauto-lane__asks"
                            title="This plan is waiting on your sign-off. Tick the approval box in the task's notes."
                          >
                            sign off
                          </span>
                        ) : t.openQuestions > 0 ? (
                          <span
                            className="taskauto-lane__asks"
                            title="This task is asking you something. The questions are in its notes."
                          >
                            {t.openQuestions} question{t.openQuestions === 1 ? '' : 's'}
                          </span>
                        ) : null}
                        {t.stuck && (
                          <span
                            className="taskauto-lane__stuck"
                            title="This task is tagged with two lanes at once, so automation can't pick it up. Remove one lane tag to fix it."
                          >
                            needs repair
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
