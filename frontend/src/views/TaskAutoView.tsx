/**
 * TaskAutoView — main view for the hadoku-task-automation pipeline.
 *
 * Two tabs:
 *   - Review — what is running plus the PRs waiting on a merge. Default,
 *     because those are the only two things that ever need a person.
 *   - Boards — every board's lanes, for when you want the whole picture.
 *
 * Uses `useTaskAutoStore` exclusively. Tab markup mirrors
 * `TemporalPipelineView` so the two pipelines read as the same product.
 */

import { useEffect, useMemo, useState } from 'react'
import { useTaskAutoStore } from '../store/taskautoStore'
import { BoardPanel, PRReviewPanel, RunningNow, TaskDetailModal } from '../components/taskauto'
import { EmptyState, LoadingState } from '../components/common'

type TabKey = 'review' | 'boards'

export function TaskAutoView() {
  const status = useTaskAutoStore(s => s.status)
  const loading = useTaskAutoStore(s => s.loading)
  const error = useTaskAutoStore(s => s.error)
  const merging = useTaskAutoStore(s => s.merging)
  const mergeError = useTaskAutoStore(s => s.mergeError)
  const mergedIds = useTaskAutoStore(s => s.mergedIds)
  const loadStatus = useTaskAutoStore(s => s.loadStatus)
  const merge = useTaskAutoStore(s => s.merge)
  const openTask = useTaskAutoStore(s => s.openTask)
  const taskDetail = useTaskAutoStore(s => s.taskDetail)
  const taskLoading = useTaskAutoStore(s => s.taskLoading)
  const taskError = useTaskAutoStore(s => s.taskError)
  const showTask = useTaskAutoStore(s => s.showTask)
  const hideTask = useTaskAutoStore(s => s.hideTask)

  const [tab, setTab] = useState<TabKey>('review')

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  const boards = useMemo(() => status?.boards ?? [], [status])
  const running = useMemo(() => status?.running ?? [], [status])
  // A PR we just merged stays in `status` until the backend re-reads GitHub;
  // drop it here so the row leaves on the merge, not on the reload.
  const prs = useMemo(
    () =>
      boards.flatMap(b => b.prs ?? []).filter(pr => !mergedIds.includes(`${pr.repo}#${pr.number}`)),
    [boards, mergedIds]
  )
  const laneOrder = status?.laneOrder ?? []

  // The board already knows the title of the task being opened, so the modal
  // can be headed correctly while its detail is still in flight.
  const openTitle = useMemo(() => {
    if (!openTask) return ''
    const board = boards.find(b => b.handle === openTask.board)
    for (const lane of Object.values(board?.lanes ?? {})) {
      const task = lane.find(t => t.id === openTask.taskId)
      if (task) return task.title
    }
    return openTask.taskId
  }, [openTask, boards])

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'review', label: 'Review', count: prs.length },
    { key: 'boards', label: 'Boards', count: boards.length }
  ]

  if (loading && !status) return <LoadingState text="Loading task automation…" />

  return (
    <div className="taskauto-view" data-testid="taskauto-view">
      <nav className="stage-tabs" data-testid="taskauto-tabs">
        {tabs.map(t => (
          <button
            key={t.key}
            type="button"
            className={`stage-tab ${tab === t.key ? 'stage-tab--active' : ''}`}
            data-testid={`taskauto-tab-${t.key}`}
            onClick={() => setTab(t.key)}
          >
            <span className="stage-tab__icon">{t.key === 'review' ? '🔀' : '📋'}</span>
            <span className="stage-tab__label">{t.label}</span>
            <span className="stage-tab__count">{t.count}</span>
          </button>
        ))}
        <div className="stage-tabs__actions">
          <button
            type="button"
            className="btn btn--primary btn--sm"
            disabled={loading}
            onClick={() => {
              void loadStatus()
            }}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </nav>

      {error && (
        <p className="taskauto-error" data-testid="taskauto-error">
          {error}
        </p>
      )}

      <div className="taskauto-view__body">
        {tab === 'review' && (
          <>
            <RunningNow running={running} />
            <PRReviewPanel
              prs={prs}
              merging={merging}
              mergeError={mergeError}
              onMerge={(repo, number, auto) => {
                void merge(repo, number, auto)
              }}
            />
          </>
        )}

        {tab === 'boards' &&
          (boards.length === 0 ? (
            <EmptyState
              icon="📋"
              title="No automation boards"
              description="Boards appear here once one is shared with the tenhands service key."
            />
          ) : (
            <div className="taskauto-boards">
              {boards.map(b => (
                <BoardPanel
                  key={b.handle}
                  board={b}
                  laneOrder={laneOrder}
                  onOpenTask={(board, taskId) => {
                    void showTask(board, taskId)
                  }}
                />
              ))}
            </div>
          ))}
      </div>

      {openTask && (
        <TaskDetailModal
          detail={taskDetail}
          loading={taskLoading}
          error={taskError}
          fallbackTitle={openTitle}
          onClose={hideTask}
        />
      )}
    </div>
  )
}
