/**
 * Stage3Assign
 *
 * Assign Copilot to vibecheck issues.
 * Includes severity and label filters.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { batchAssignCopilot } from '../../api/endpoints'
import type { Issue } from '../../api/types'
import { getSeverity, getSeverityClass } from '../../utils'

export function Stage3Assign() {
  const stage3 = usePipelineStore(state => state.stage3)
  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const removeStage3Issue = usePipelineStore(state => state.removeStage3Issue)

  const [selectedIssues, setSelectedIssues] = useState<Set<string>>(new Set())
  const [selectedRecommended, setSelectedRecommended] = useState<Set<string>>(new Set())
  const [assigning, setAssigning] = useState(false)

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

    return filtered
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
    return Object.values(repoIssues)
  }, [filteredIssues, reposWithCopilotPRs])

  // Available labels for filter (excluding severity/confidence/vibeCheck)
  const availableLabels = labels.filter(
    label =>
      label &&
      !label.startsWith('severity:') &&
      !label.startsWith('confidence:') &&
      label !== 'vibeCheck'
  )

  const makeIssueKey = (issue: Issue) => `${issue.repo}:${issue.number}`

  const toggleIssue = (issue: Issue, isRecommended: boolean) => {
    const key = makeIssueKey(issue)
    const setter = isRecommended ? setSelectedRecommended : setSelectedIssues
    setter(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  const selectAll = () => {
    setSelectedIssues(new Set(filteredIssues.map(makeIssueKey)))
  }

  const selectNone = () => {
    setSelectedIssues(new Set())
  }

  const selectAllRecommended = () => {
    setSelectedRecommended(new Set(recommended.map(makeIssueKey)))
  }

  const assignRecommended = async () => {
    if (!owner || selectedRecommended.size === 0) return

    setAssigning(true)
    addLog(`Assigning Copilot to ${selectedRecommended.size} recommended issues...`, 'info')

    const issues = Array.from(selectedRecommended).map(key => {
      const [repo, issueNumber] = key.split(':')
      return { repo, issueNumber: parseInt(issueNumber) }
    })

    let successCount = 0

    await batchAssignCopilot(owner, issues, (completed, total, result) => {
      if (result.success) {
        successCount++
        addLog(`Assigned to ${result.repo}#${result.issueNumber}`, 'success')
        // Immediately remove from UI
        removeStage3Issue(result.repo, result.issueNumber)
        // Also remove from selection
        setSelectedRecommended(prev => {
          const next = new Set(prev)
          next.delete(`${result.repo}:${result.issueNumber}`)
          return next
        })
      } else {
        addLog(`Failed on ${result.repo}#${result.issueNumber}: ${result.error}`, 'error')
      }
    })

    addLog(
      `Done! Assigned Copilot to ${successCount}/${issues.length} issues`,
      successCount > 0 ? 'success' : 'error'
    )
    setAssigning(false)
    setSelectedRecommended(new Set())
  }

  const assignSelected = async () => {
    const allSelected = new Set([...selectedRecommended, ...selectedIssues])
    if (!owner || allSelected.size === 0) return

    setAssigning(true)
    addLog(`Assigning Copilot to ${allSelected.size} issues...`, 'info')

    const issues = Array.from(allSelected).map(key => {
      const [repo, issueNumber] = key.split(':')
      return { repo, issueNumber: parseInt(issueNumber) }
    })

    let successCount = 0

    await batchAssignCopilot(owner, issues, (completed, total, result) => {
      if (result.success) {
        successCount++
        addLog(`Assigned to ${result.repo}#${result.issueNumber}`, 'success')
        // Immediately remove from UI
        removeStage3Issue(result.repo, result.issueNumber)
        // Also remove from selections
        const key = `${result.repo}:${result.issueNumber}`
        setSelectedIssues(prev => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
        setSelectedRecommended(prev => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
      } else {
        addLog(`Failed on ${result.repo}#${result.issueNumber}: ${result.error}`, 'error')
      }
    })

    addLog(
      `Done! Assigned Copilot to ${successCount}/${issues.length} issues`,
      successCount > 0 ? 'success' : 'error'
    )
    setAssigning(false)
    setSelectedIssues(new Set())
    setSelectedRecommended(new Set())
  }

  // Loading state
  if (stage3.loading && allIssues.length === 0) {
    return (
      <div className="loading-state">
        <div className="loading-state__spinner" />
        <p className="loading-state__text">Loading issues...</p>
      </div>
    )
  }

  // Empty state
  if (allIssues.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">📭</div>
        <h3 className="empty-state__title">No issues to assign</h3>
        <p className="empty-state__description">
          Run VibeCheck on repos in Stage 2 to create issues.
        </p>
      </div>
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
              <button className="btn btn--secondary btn--sm" onClick={selectAllRecommended}>
                Select All
              </button>
              <button
                className="btn btn--warning btn--sm"
                onClick={() => {
                  void assignRecommended()
                }}
                disabled={assigning || selectedRecommended.size === 0}
              >
                Assign Recommended ({selectedRecommended.size})
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
                </tr>
              </thead>
              <tbody>
                {recommended.map(issue => (
                  <IssueRow
                    key={makeIssueKey(issue)}
                    issue={issue}
                    checked={selectedRecommended.has(makeIssueKey(issue))}
                    onChange={() => toggleIssue(issue, true)}
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
            <button className="btn btn--secondary btn--sm" onClick={selectAll}>
              Select All
            </button>
            <button className="btn btn--secondary btn--sm" onClick={selectNone}>
              Select None
            </button>
            <button
              className="btn btn--primary btn--sm"
              onClick={() => {
                void assignSelected()
              }}
              disabled={assigning || (selectedIssues.size === 0 && selectedRecommended.size === 0)}
            >
              Assign Selected ({selectedIssues.size + selectedRecommended.size})
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
                  <th>Labels</th>
                </tr>
              </thead>
              <tbody>
                {filteredIssues.map(issue => (
                  <IssueRow
                    key={makeIssueKey(issue)}
                    issue={issue}
                    checked={selectedIssues.has(makeIssueKey(issue))}
                    onChange={() => toggleIssue(issue, false)}
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
