/**
 * StageDetails Component
 *
 * Expanded content showing details of a pipeline item.
 */

import { useState, useCallback } from 'react'
import type { PipelineItem, Issue, PullRequest } from '../../api/types'
import { usePipelineStore, useReviewQueueStore } from '../../store'
import { assignCopilot } from '../../api/endpoints'
import {
  getSeverityFromLabels,
  getSeverityLabel,
  getSeverityColor,
  getErrorMessage
} from '../../utils'
import { useReviewActions } from '../../hooks'

interface StageDetailsProps {
  item: PipelineItem
}

export function StageDetails({ item }: StageDetailsProps) {
  const [assignLoading, setAssignLoading] = useState(false)
  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const loadStage3 = usePipelineStore(state => state.loadStage3)
  const loadStage4 = usePipelineStore(state => state.loadStage4)
  const setActiveView = usePipelineStore(state => state.setActiveView)
  const setQueue = useReviewQueueStore(state => state.setQueue)

  const { actionLoading, approve, merge } = useReviewActions({
    owner,
    addLog,
    onAfterApprove: useCallback(() => loadStage4(), [loadStage4]),
    onAfterMerge: useCallback(() => loadStage4(), [loadStage4])
  })

  // Render based on item type
  if (item.id.startsWith('issue-')) {
    return renderIssueDetails(item.data as Issue)
  }

  if (item.id.startsWith('pr-')) {
    return renderPRDetails(item.data as PullRequest)
  }

  return <div className="stage-details-empty">No details available</div>

  function renderIssueDetails(issue: Issue) {
    const severity = getSeverityFromLabels(issue.labels)

    const handleAssignCopilot = async () => {
      if (!owner) return
      setAssignLoading(true)
      try {
        const result = await assignCopilot(owner, item.repo, issue.number)
        if (result.success) {
          addLog(`Assigned Copilot to ${item.repo}#${issue.number}`, 'success')
          await loadStage3()
        } else {
          addLog(`Failed: ${result.error}`, 'error')
        }
      } catch (err) {
        addLog(`Error: ${getErrorMessage(err)}`, 'error')
      } finally {
        setAssignLoading(false)
      }
    }

    return (
      <div className="stage-details stage-details-issue">
        <div className="details-header">
          <h4 className="details-title">{issue.title}</h4>
          <a href={issue.url} target="_blank" rel="noopener noreferrer" className="details-link">
            View on GitHub
          </a>
        </div>

        <div className="details-meta">
          <div className="meta-item">
            <span className="meta-label">Severity:</span>
            <span className="meta-value" style={{ color: getSeverityColor(severity) }}>
              {getSeverityLabel(severity)}
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Labels:</span>
            <span className="meta-value">{issue.labels.map(l => l.name).join(', ') || 'None'}</span>
          </div>
        </div>

        {issue.body && (
          <div className="details-body">
            <p>{issue.body}</p>
          </div>
        )}

        <div className="details-actions">
          <button
            className="action-btn action-btn-primary"
            onClick={() => {
              void handleAssignCopilot()
            }}
            disabled={assignLoading}
          >
            {assignLoading ? 'Assigning...' : 'Assign Copilot'}
          </button>
          <button
            className="action-btn action-btn-secondary"
            onClick={() => {
              // Could implement yolo mode here
              addLog('Yolo mode not yet implemented', 'warning')
            }}
          >
            Yolo (Skip Review)
          </button>
        </div>
      </div>
    )
  }

  function renderPRDetails(pr: PullRequest) {
    const handleViewInReview = () => {
      // Set this PR as the only item in the review queue and switch to review view
      const pipelineItems = usePipelineStore.getState().pipelineItems
      const thisItem = pipelineItems.find(i => i.id === item.id)
      if (thisItem) {
        setQueue([thisItem])
        setActiveView('review')
      }
    }

    return (
      <div className="stage-details stage-details-pr">
        <div className="details-header">
          <h4 className="details-title">{pr.title}</h4>
          <a href={pr.url} target="_blank" rel="noopener noreferrer" className="details-link">
            View on GitHub
          </a>
        </div>

        <div className="details-meta">
          <div className="meta-item">
            <span className="meta-label">Author:</span>
            <span className="meta-value">{pr.author?.login || 'Unknown'}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Branch:</span>
            <span className="meta-value">
              {pr.headRefName} → {pr.baseRefName}
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Status:</span>
            <span className="meta-value">
              {pr.isDraft ? 'Draft' : 'Ready'}
              {pr.reviewDecision && ` • ${pr.reviewDecision}`}
            </span>
          </div>
          {pr.copilotCompleted !== null && (
            <div className="meta-item">
              <span className="meta-label">Copilot:</span>
              <span className="meta-value">
                {pr.copilotCompleted ? 'Completed' : 'In Progress'}
              </span>
            </div>
          )}
        </div>

        <div className="details-actions">
          <button className="action-btn action-btn-primary" onClick={handleViewInReview}>
            View Diff
          </button>
          <button
            className="action-btn action-btn-secondary"
            onClick={() => {
              void approve(item.repo, pr.number)
            }}
            disabled={actionLoading}
          >
            {actionLoading ? 'Processing...' : 'Approve'}
          </button>
          <button
            className="action-btn action-btn-success"
            onClick={() => {
              void merge(item.repo, pr.number)
            }}
            disabled={actionLoading}
          >
            {actionLoading ? 'Processing...' : 'Merge'}
          </button>
        </div>
      </div>
    )
  }
}
