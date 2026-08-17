/**
 * TaskAutoView — main view for the hadoku-task-automation pipeline.
 *
 * Two tabs:
 *   - Review — what is running plus the PRs waiting on a merge. Default,
 *     because those are the only two things that ever need a person.
 *   - Boards — every board's lanes, for when you want the whole picture.
 *
 * Uses `useTaskAutoStore` exclusively. The tab strip is the shared
 * `StageTabView`, so the pipelines read as the same product.
 */

import { useEffect, useMemo, useState } from 'react'
import { useTaskAutoStore } from '../store/taskautoStore'
import { BoardPanel, PRReviewPanel, RunningNow, TaskDetailModal } from '../components/taskauto'
import { EmptyState, LoadingState, StageTabView } from '../components/common'

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

  if (loading && !status) return <LoadingState text="Loading task automation…" />

  return (
    <div className="taskauto-view" data-testid="taskauto-view">
      <StageTabView
        testId="taskauto-tabs"
        stages={[
          {
            id: 'review',
            label: 'Review',
            icon: 'shuffle',
            getCount: () => prs.length,
            testId: 'taskauto-tab-review'
          },
          {
            id: 'boards',
            label: 'Boards',
            icon: 'clipboard',
            getCount: () => boards.length,
            testId: 'taskauto-tab-boards'
          }
        ]}
        activeId={tab}
        onChange={id => setTab(id as TabKey)}
        isLoading={loading}
        onRefreshAll={() => {
          void loadStatus()
        }}
        refreshLabel="Refresh"
      />

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
              icon="clipboard"
              title="No automation boards"
              description="Boards appear here once they're connected to the automation account."
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
