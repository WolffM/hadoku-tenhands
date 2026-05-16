/**
 * BatchBrowser - batch + run browser for the Active and Archive tabs.
 *
 * Two columns: a left rail (batch list, with the selected batch's runs
 * nested under it) and the issue detail on the right. The inbox is NOT
 * here - it lives on its own tab - so there's no vertical scrolling past
 * an inbox to reach a run.
 *
 * On mount (and whenever the tab's batch set changes) the first batch is
 * auto-selected, and once its detail loads the first run is auto-selected
 * too - the operator always lands on something instead of an empty pane.
 */

import { useEffect } from 'react'
import { useTemporalStore } from '../../store/temporalStore'
import type { TemporalBatchSummary } from '../../api/types'
import { IssueDetail } from './IssueDetail'
import { StateBadge } from './StateBadge'

interface BatchBrowserProps {
  batches: TemporalBatchSummary[]
  emptyText: string
}

export function BatchBrowser({ batches, emptyText }: BatchBrowserProps) {
  const batchDetail = useTemporalStore(s => s.batchDetail)
  const selectedBatchId = useTemporalStore(s => s.selectedBatchId)
  const selectedIssueId = useTemporalStore(s => s.selectedIssueId)
  const loadBatch = useTemporalStore(s => s.loadBatch)
  const selectIssue = useTemporalStore(s => s.selectIssue)

  // Auto-select the first batch in this tab if nothing here is selected.
  useEffect(() => {
    if (batches.length === 0) return
    const selectionInTab = batches.some(b => b.batch_id === selectedBatchId)
    if (!selectionInTab) {
      void loadBatch(batches[0].batch_id)
    }
  }, [batches, selectedBatchId, loadBatch])

  // Once the selected batch's detail lands, auto-select its first run.
  useEffect(() => {
    const d = batchDetail.data
    if (!d || d.batch_id !== selectedBatchId || d.issues.length === 0) return
    const hasValidSelection =
      selectedIssueId !== null && d.issues.some(i => i.issue_id === selectedIssueId)
    if (!hasValidSelection) {
      selectIssue(d.issues[0].issue_id)
    }
  }, [batchDetail.data, selectedBatchId, selectedIssueId, selectIssue])

  if (batches.length === 0) {
    return (
      <p className="temporal-browser__empty" data-testid="temporal-browser-empty">
        {emptyText}
      </p>
    )
  }

  const detail = batchDetail.data
  const runsForSelectedBatch = detail && detail.batch_id === selectedBatchId ? detail.issues : []

  return (
    <div className="temporal-browser" data-testid="temporal-batches-pane">
      <aside className="temporal-browser__rail">
        <ul className="temporal-browser__batch-list">
          {batches.map(b => {
            const isActiveBatch = b.batch_id === selectedBatchId
            const countLabel =
              (b.deferred_count ? `${b.deferred_count} deferred / ` : '') + `${b.issue_count} runs`
            return (
              <li key={b.batch_id}>
                <button
                  type="button"
                  data-testid="temporal-batch-button"
                  data-batch-id={b.batch_id}
                  data-active={isActiveBatch}
                  onClick={() => {
                    void loadBatch(b.batch_id)
                  }}
                >
                  <span className="temporal-browser__batch-name">{b.batch_id}</span>
                  <span className="temporal-browser__batch-count">{countLabel}</span>
                </button>

                {isActiveBatch && (
                  <ul className="temporal-browser__run-list" data-testid="temporal-issues-list">
                    {batchDetail.loading && runsForSelectedBatch.length === 0 && (
                      <li className="temporal-browser__run-loading">Loading runs...</li>
                    )}
                    {runsForSelectedBatch.map(i => (
                      <li key={i.issue_id}>
                        <button
                          type="button"
                          data-testid="temporal-issue-button"
                          data-issue-id={i.issue_id}
                          data-active={selectedIssueId === i.issue_id}
                          onClick={() => selectIssue(i.issue_id)}
                        >
                          <span className="temporal-browser__run-name">{i.issue_id}</span>
                          <StateBadge
                            state={i.current_state}
                            isDeferred={i.is_deferred}
                            abortKind={i.abort_kind}
                          />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )
          })}
        </ul>
      </aside>

      <div className="temporal-browser__detail">
        {selectedBatchId && selectedIssueId ? (
          <IssueDetail batchId={selectedBatchId} issueId={selectedIssueId} />
        ) : (
          <p data-testid="temporal-detail-empty">
            Select a run to see evidence, gates, and timeline.
          </p>
        )}
      </div>
    </div>
  )
}
