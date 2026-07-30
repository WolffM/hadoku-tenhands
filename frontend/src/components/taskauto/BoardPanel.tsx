/**
 * BoardPanel — one automation board as a row of lanes.
 *
 * Lanes are rendered in the board's own order (the API sends `laneOrder`)
 * rather than an order invented here, so adding a lane to the schema shows up
 * without a frontend change.
 *
 * A task carrying two lane tags resolves to no lane at all, which makes it
 * invisible to the scheduler — it sits there looking fine and is never picked
 * up. That failure has happened twice in production, so it gets a loud marker
 * rather than being folded into a count.
 */

import { Badge, type BadgeVariant } from '../common'
import type { TaskAutoBoard } from '../../api/types'

/** Lanes where the pipeline is waiting on a person, not on itself. */
const HUMAN_LANES = new Set(['plan-review', 'replan', 'approved', 'stalled'])

function laneVariant(lane: string): BadgeVariant {
  if (lane === 'stalled') return 'danger'
  if (HUMAN_LANES.has(lane)) return 'warning'
  if (lane === '(inbox)') return 'secondary'
  return 'info'
}

interface BoardPanelProps {
  board: TaskAutoBoard
  laneOrder: string[]
  /** Open one task's full history. */
  onOpenTask: (board: string, taskId: string) => void
}

export function BoardPanel({ board, laneOrder, onOpenTask }: BoardPanelProps) {
  const total = Object.values(board.lanes).reduce((n, tasks) => n + tasks.length, 0)

  return (
    <section className="taskauto-board" data-testid={`taskauto-board-${board.handle}`}>
      <header className="taskauto-board__head">
        <h3 className="taskauto-board__name">{board.name}</h3>
        <code className="taskauto-board__repo">{board.repo}</code>
        <span className="taskauto-board__total">
          {total} task{total === 1 ? '' : 's'}
        </span>
      </header>

      {board.error ? (
        <p className="taskauto-board__error">{board.error}</p>
      ) : (
        <div className="taskauto-lanes">
          {laneOrder.map(lane => {
            const tasks = board.lanes[lane] ?? []
            if (tasks.length === 0) return null
            return (
              <div key={lane} className="taskauto-lane">
                <div className="taskauto-lane__head">
                  <Badge variant={laneVariant(lane)}>{lane}</Badge>
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
                        {t.stuck && (
                          <span
                            className="taskauto-lane__stuck"
                            title="Two lane tags — the scheduler cannot see this task. It needs repair."
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
