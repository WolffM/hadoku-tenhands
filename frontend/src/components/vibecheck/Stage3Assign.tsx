/**
 * Stage3Assign
 *
 * Assign Copilot to vibecheck issues.
 * Includes severity and label filters.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { assignCopilot } from '../../api/endpoints'
import { useBatchAction } from '../../hooks'
import type { Issue } from '../../api/types'
import { getSeverity, getSeverityClass, formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'

export function Stage3Assign() {
  const stage3 = usePipelineStore(state => state.stage3)
  const owner = usePipelineStore(state => state.owner)
  const removeStage3Issue = usePipelineStore(state => state.removeStage3Issue)

  // Filters
  const [severityFilter, setSeverityFilter] = useState('all')
  const [labelFilter, setLabelFilter] = useState('all')

  const allIssues = stage3.items
  const labels = stage3.labels
  const reposWithCopilotPRs = stage3.reposWithCopilotPRs

  // Filter issues
  const filteredIssues = useMemo(() => {
    let filtered = allIssues

    if (severityFilter !== 'all') {
      filtered = filtered.filter(issue =>
        issue.labels.some(l => l.name.toLowerCase().includes(severityFilter.toLowerCase()))
      )
    }

    if (labelFilter !== 'all') {
      filtered = filtered.filter(issue => issue.labels.some(l => l.name === labelFilter))
    }

    // Sort by created date (oldest first)
    return [...filtered].sort((a, b) => {
      const dateA = new Date(a.createdAt).getTime()
      const dateB = new Date(b.createdAt).getTime()
      return dateA - dateB
    })
  }, [allIssues, severityFilter, labelFilter])

  // Get recommended issues (1 per repo, no active Copilot PRs)
  const recommended = useMemo(() => {
    const repoIssues: Record<string, Issue> = {}
    for (const issue of filteredIssues) {
      const repo = issue.repo ?? ''
      if (reposWithCopilotPRs.includes(repo)) continue
      if (!repoIssues[repo]) {
        repoIssues[repo] = issue
      }
    }
    // Sort by created date (oldest first)
    return Object.values(repoIssues).sort((a, b) => {
      const dateA = new Date(a.createdAt).getTime()
      const dateB = new Date(b.createdAt).getTime()
      return dateA - dateB
    })
  }, [filteredIssues, reposWithCopilotPRs])

  // Available labels for filter (excluding severity/confidence/vibeCheck)
  const availableLabels = labels.filter(
    label =>
      label &&
      !label.startsWith('severity:') &&
      !label.startsWith('confidence:') &&
      label !== 'vibeCheck'
  )

  // Batch action for assigning Copilot
  const {
    processing: assigning,
    selectedCount,
    toggleItem,
    selectAll,
    selectNone,
    isSelected,
    processSelected
  } = useBatchAction<Issue>({
    processItem: async issue => {
      if (!owner) return { success: false, error: 'No owner' }
      const result = await assignCopilot(owner, issue.repo ?? '', issue.number)
      return { success: result.success, error: result.error }
    },
    getItemId: issue => `${issue.repo}:${issue.number}`,
    getItemName: issue => `${issue.repo}#${issue.number}`,
    onItemSuccess: issue => removeStage3Issue(issue.repo ?? '', issue.number),
    actionVerb: 'Assigned'
  })

  // Loading state
  if (stage3.loading && allIssues.length === 0) {
    return <LoadingState text="Loading issues..." />
  }

  // Empty state
  if (allIssues.length === 0) {
    return (
      <EmptyState
        icon="📭"
        title="No issues to assign"
        description="Run VibeCheck on repos in Stage 2 to create issues."
      />
    )
  }

  return (
    <div className="stage-panel">
      {/* Filters */}
      <div className="filter-bar">
        <div className="filter-group">
          <label className="filter-label">Severity</label>
          <select
            className="filter-select"
            value={severityFilter}
            onChange={e => setSeverityFilter(e.target.value)}
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div className="filter-group">
          <label className="filter-label">Label</label>
          <select
            className="filter-select"
            value={labelFilter}
            onChange={e => setLabelFilter(e.target.value)}
          >
            <option value="all">All Labels</option>
            {availableLabels.map(label => (
              <option key={label} value={label}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Recommended Section */}
      {recommended.length > 0 && (
        <div className="stage-section stage-section--recommended">
          <div className="stage-section__header">
            <h3 className="stage-section__title">
              <span className="stage-section__icon">⭐</span>
              Recommended (1 per repo, no active Copilot PRs)
            </h3>
            <div className="stage-section__actions">
              <button className="btn btn--secondary btn--sm" onClick={() => selectAll(recommended)}>
                Select All
              </button>
              <button
                className="btn btn--warning btn--sm"
                onClick={() => {
                  void processSelected(recommended)
                }}
                disabled={assigning || selectedCount === 0}
              >
                Assign Recommended ({selectedCount})
              </button>
            </div>
          </div>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '30px' }}></th>
                  <th>Repo</th>
                  <th>#</th>
                  <th>Title</th>
                  <th>Severity</th>
                  <th>Created Date</th>
                </tr>
              </thead>
              <tbody>
                {recommended.map(issue => (
                  <IssueRow
                    key={`${issue.repo}:${issue.number}`}
                    issue={issue}
                    checked={isSelected(issue)}
                    onChange={() => toggleItem(issue)}
                    disabled={assigning}
                    showLabels={false}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Divider */}
      {recommended.length > 0 && <hr className="stage-divider" />}

      {/* All Issues Section */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">All Issues</h3>
          <div className="stage-section__actions">
            <button
              className="btn btn--secondary btn--sm"
              onClick={() => selectAll(filteredIssues)}
            >
              Select All
            </button>
            <button className="btn btn--secondary btn--sm" onClick={selectNone}>
              Select None
            </button>
            <button
              className="btn btn--primary btn--sm"
              onClick={() => {
                void processSelected(filteredIssues)
              }}
              disabled={assigning || selectedCount === 0}
            >
              Assign Selected ({selectedCount})
            </button>
          </div>
        </div>

        {filteredIssues.length === 0 ? (
          <p className="text-secondary text-center">No issues found matching filters</p>
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '30px' }}></th>
                  <th>Repo</th>
                  <th>#</th>
                  <th>Title</th>
                  <th>Severity</th>
                  <th>Created Date</th>
                  <th>Labels</th>
                </tr>
              </thead>
              <tbody>
                {filteredIssues.map(issue => (
                  <IssueRow
                    key={`${issue.repo}:${issue.number}`}
                    issue={issue}
                    checked={isSelected(issue)}
                    onChange={() => toggleItem(issue)}
                    disabled={assigning}
                    showLabels
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

interface IssueRowProps {
  issue: Issue
  checked: boolean
  onChange: () => void
  disabled: boolean
  showLabels: boolean
}

function IssueRow({ issue, checked, onChange, disabled, showLabels }: IssueRowProps) {
  const severity = getSeverity(issue)
  const severityClass = getSeverityClass(severity)

  const otherLabels = issue.labels
    .filter(
      l =>
        !l.name.startsWith('severity:') &&
        l.name !== 'vibeCheck' &&
        !l.name.startsWith('confidence:')
    )
    .slice(0, 2)

  const displayTitle = issue.title.length > 45 ? issue.title.substring(0, 45) + '...' : issue.title

  return (
    <tr>
      <td>
        <input
          type="checkbox"
          className="checkbox"
          checked={checked}
          onChange={onChange}
          disabled={disabled}
        />
      </td>
      <td>
        <span className="repo-link">{issue.repo}</span>
      </td>
      <td className="text-light">{issue.number}</td>
      <td>
        <a
          href={issue.url}
          target="_blank"
          rel="noopener noreferrer"
          className="issue-link"
          title={issue.title}
        >
          {displayTitle}
        </a>
      </td>
      <td>
        <span className={severityClass}>{severity}</span>
      </td>
      <td className="text-light">{formatTimeAgo(issue.createdAt)}</td>
      {showLabels && (
        <td>
          {otherLabels.map(l => (
            <span key={l.name} className="badge badge--secondary">
              {l.name}
            </span>
          ))}
        </td>
      )}
    </tr>
  )
}
