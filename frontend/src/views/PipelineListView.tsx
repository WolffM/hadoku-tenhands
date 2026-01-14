/**
 * PipelineListView
 *
 * Main view showing all pipeline items as expandable rows.
 */

import { useEffect } from 'react'
import { usePipelineStore, selectIsLoading } from '../store'
import { PipelineRow } from '../components/pipeline'
import { ProgressLog } from '../components/common'

export function PipelineListView() {
  const pipelineItems = usePipelineStore(state => state.pipelineItems)
  const isLoading = usePipelineStore(selectIsLoading)
  const loadAllStages = usePipelineStore(state => state.loadAllStages)
  const selectedItems = usePipelineStore(state => state.selectedItems)
  const selectAll = usePipelineStore(state => state.selectAll)
  const selectNone = usePipelineStore(state => state.selectNone)

  // Load data on mount
  useEffect(() => {
    void loadAllStages()
  }, [loadAllStages])

  const selectedCount = selectedItems.size
  const totalCount = pipelineItems.length

  return (
    <div className="pipeline-list-view">
      {/* Toolbar */}
      <div className="pipeline-toolbar">
        <div className="toolbar-left">
          <span className="toolbar-count">
            {totalCount} pipeline items
            {selectedCount > 0 && ` (${selectedCount} selected)`}
          </span>
        </div>
        <div className="toolbar-right">
          <button className="toolbar-btn" onClick={selectAll} disabled={totalCount === 0}>
            Select All
          </button>
          <button className="toolbar-btn" onClick={selectNone} disabled={selectedCount === 0}>
            Select None
          </button>
          <button
            className="toolbar-btn toolbar-btn-primary"
            onClick={() => {
              void loadAllStages()
            }}
            disabled={isLoading}
          >
            {isLoading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && pipelineItems.length === 0 && (
        <div className="loading-state">
          <p>Loading pipeline items...</p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && pipelineItems.length === 0 && (
        <div className="empty-state">
          <h3>No pipeline items</h3>
          <p>
            There are no active pipeline items. Issues will appear here when VibeCheck creates them.
          </p>
        </div>
      )}

      {/* Pipeline items list */}
      {pipelineItems.length > 0 && (
        <div className="pipeline-list">
          {pipelineItems.map(item => (
            <PipelineRow key={item.id} item={item} />
          ))}
        </div>
      )}

      {/* Progress log */}
      <ProgressLog />
    </div>
  )
}
