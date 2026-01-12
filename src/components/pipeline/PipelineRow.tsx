/**
 * PipelineRow Component
 *
 * Collapsible row showing a pipeline item with progress.
 */

import type { PipelineItem, Issue, PullRequest } from '../../api/types'
import { usePipelineStore } from '../../store'
import { formatTimeAgo } from '../../utils'
import { StatusBadge } from '../common/StatusBadge'
import { ProgressBar } from './ProgressBar'
import { StageDetails } from './StageDetails'

interface PipelineRowProps {
  item: PipelineItem
}

export function PipelineRow({ item }: PipelineRowProps) {
  const expandedRows = usePipelineStore(state => state.expandedRows)
  const toggleRowExpanded = usePipelineStore(state => state.toggleRowExpanded)
  const selectedItems = usePipelineStore(state => state.selectedItems)
  const toggleItemSelected = usePipelineStore(state => state.toggleItemSelected)

  const isExpanded = expandedRows.has(item.id)
  const isSelected = selectedItems.has(item.id)

  // Get title from underlying data
  const getTitle = (): string => {
    if (item.id.startsWith('issue-')) {
      return (item.data as Issue).title
    }
    if (item.id.startsWith('pr-')) {
      return (item.data as PullRequest).title
    }
    return item.identifier
  }

  return (
    <div className={`pipeline-row ${isExpanded ? 'pipeline-row-expanded' : ''}`}>
      <div className="pipeline-row-header" onClick={() => toggleRowExpanded(item.id)}>
        <div className="pipeline-row-select" onClick={e => e.stopPropagation()}>
          <input
            type="checkbox"
            checked={isSelected}
            onChange={() => toggleItemSelected(item.id)}
            title="Select for batch action"
          />
        </div>

        <div className="pipeline-row-expand">
          <span className={`expand-icon ${isExpanded ? 'expanded' : ''}`}>▶</span>
        </div>

        <div className="pipeline-row-info">
          <div className="pipeline-row-primary">
            <span className="pipeline-repo">{item.repo}</span>
            <span className="pipeline-separator">/</span>
            <span className="pipeline-identifier">{item.identifier}</span>
          </div>
          <div className="pipeline-row-secondary">
            <span className="pipeline-title" title={getTitle()}>
              {getTitle()}
            </span>
          </div>
        </div>

        <div className="pipeline-row-progress">
          <ProgressBar current={item.currentStage} total={item.totalStages} />
        </div>

        <div className="pipeline-row-stage">
          <span className="stage-name">{item.stageName}</span>
        </div>

        <div className="pipeline-row-status">
          <StatusBadge status={item.status} size="sm" />
        </div>

        <div className="pipeline-row-time">
          <span className="time-ago" title={item.updatedAt}>
            {formatTimeAgo(item.updatedAt)}
          </span>
        </div>
      </div>

      {isExpanded && (
        <div className="pipeline-row-content">
          <StageDetails item={item} />
        </div>
      )}
    </div>
  )
}
