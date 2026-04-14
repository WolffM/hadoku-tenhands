/**
 * TemporalPipelineView — main view for the crimson-kitty pipeline.
 *
 * Three panes:
 *   - batches list (left)
 *   - inbox (right top)
 *   - selected issue detail (right bottom)
 *
 * Uses `useTemporalStore` exclusively — the composite `usePipelineStore`
 * is not used here because the temporal pipeline has its own data shape.
 */

import { useEffect } from 'react'
import { useTemporalStore } from '../store/temporalStore'
import { PipelineInbox, IssueDetail, StateBadge } from '../components/temporal'

export function TemporalPipelineView() {
  const batches = useTemporalStore(s => s.batches)
  const batchDetail = useTemporalStore(s => s.batchDetail)
  const selectedBatchId = useTemporalStore(s => s.selectedBatchId)
  const selectedIssueId = useTemporalStore(s => s.selectedIssueId)
  const loadBatches = useTemporalStore(s => s.loadBatches)
  const loadBatch = useTemporalStore(s => s.loadBatch)
  const selectIssue = useTemporalStore(s => s.selectIssue)

  useEffect(() => {
    void loadBatches()
  }, [loadBatches])

  return (
    <div className="temporal-pipeline-view" data-testid="temporal-pipeline-view">
      <div className="temporal-pipeline-view__layout">
        <aside className="temporal-pipeline-view__batches" data-testid="temporal-batches-pane">
          <header>
            <h2>Batches</h2>
            <button
              type="button"
              onClick={() => {
                void loadBatches()
              }}
              disabled={batches.loading}
            >
              Refresh
            </button>
          </header>
          {batches.error && (
            <div className="temporal-pipeline-view__error" data-testid="temporal-batches-error">
              {batches.error}
            </div>
          )}
          {batches.items.length === 0 ? (
            <p data-testid="temporal-batches-empty">
              {batches.loading
                ? 'Loading…'
                : 'No batches yet. Dispatch one with POST /api/temporal/dispatch.'}
            </p>
          ) : (
            <ul className="temporal-pipeline-view__batch-list">
              {batches.items.map(b => (
                <li key={b.batch_id}>
                  <button
                    type="button"
                    data-testid="temporal-batch-button"
                    data-batch-id={b.batch_id}
                    data-active={selectedBatchId === b.batch_id}
                    onClick={() => {
                      void loadBatch(b.batch_id)
                    }}
                  >
                    {b.batch_id} ({b.issue_count})
                  </button>
                </li>
              ))}
            </ul>
          )}

          {batchDetail.data && (
            <div className="temporal-pipeline-view__issues" data-testid="temporal-issues-list">
              <h3>Issues in {batchDetail.data.batch_id}</h3>
              <ul>
                {batchDetail.data.issues.map(i => (
                  <li key={i.issue_id}>
                    <button
                      type="button"
                      data-testid="temporal-issue-button"
                      data-issue-id={i.issue_id}
                      data-active={selectedIssueId === i.issue_id}
                      onClick={() => selectIssue(i.issue_id)}
                    >
                      <span>{i.issue_id}</span>
                      <StateBadge state={i.current_state} />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        <div className="temporal-pipeline-view__main">
          <div className="temporal-pipeline-view__inbox-pane">
            <PipelineInbox />
          </div>
          <div className="temporal-pipeline-view__detail-pane">
            {selectedBatchId && selectedIssueId ? (
              <IssueDetail batchId={selectedBatchId} issueId={selectedIssueId} />
            ) : (
              <p data-testid="temporal-detail-empty">
                Select an issue from a batch to see evidence, gates, and transitions.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
