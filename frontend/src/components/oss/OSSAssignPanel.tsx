/**
 * OSSAssignPanel — Stage 3
 *
 * Fork upstream repos, create context issues, and assign Copilot.
 * Includes a manual input form for M1 testing (no Stage 2 data yet).
 */

import { useState, type FormEvent } from 'react'
import { usePipelineStore } from '../../store'
import { forkAndAssign } from '../../api/endpoints'
import type { OSSAssignment } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'

export function OSSAssignPanel() {
  const ossStage3 = usePipelineStore(state => state.ossStage3)
  const loadOSSStage3 = usePipelineStore(state => state.loadOSSStage3)
  const addLog = usePipelineStore(state => state.addLog)

  const [formData, setFormData] = useState({
    originOwner: '',
    repo: '',
    issueNumber: '',
    issueTitle: '',
    issueUrl: ''
  })
  const [assigning, setAssigning] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!formData.originOwner || !formData.repo || !formData.issueNumber) return

    setAssigning(true)
    addLog(
      `Forking ${formData.originOwner}/${formData.repo} and assigning issue #${formData.issueNumber}...`,
      'info'
    )

    try {
      const result = await forkAndAssign(
        formData.originOwner,
        formData.repo,
        parseInt(formData.issueNumber),
        formData.issueTitle || `Issue #${formData.issueNumber}`,
        formData.issueUrl ||
          `https://github.com/${formData.originOwner}/${formData.repo}/issues/${formData.issueNumber}`
      )

      if (result.success) {
        if (result.already_assigned) {
          addLog(
            `Already assigned: ${formData.originOwner}/${formData.repo}#${formData.issueNumber}`,
            'warning'
          )
        } else {
          addLog(`Assigned! Fork issue: ${result.fork_issue_url}`, 'success')
        }
        setFormData({ originOwner: '', repo: '', issueNumber: '', issueTitle: '', issueUrl: '' })
        void loadOSSStage3()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to fork and assign', 'error')
    } finally {
      setAssigning(false)
    }
  }

  const assignments = ossStage3.items

  if (ossStage3.loading && assignments.length === 0) {
    return <LoadingState text="Loading assignments..." />
  }

  return (
    <div className="stage-panel">
      {/* Manual Input Form */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            <span className="stage-section__icon">{'\u{1F531}'}</span>
            Fork & Assign Issue
          </h3>
        </div>

        <form
          onSubmit={e => {
            void handleSubmit(e)
          }}
          className="oss-assign-form"
        >
          <div className="form-row">
            <div className="form-group">
              <label className="filter-label">Owner</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. fastify"
                value={formData.originOwner}
                onChange={e => setFormData(prev => ({ ...prev, originOwner: e.target.value }))}
                required
              />
            </div>
            <div className="form-group">
              <label className="filter-label">Repo</label>
              <input
                type="text"
                className="form-input"
                placeholder="e.g. fastify"
                value={formData.repo}
                onChange={e => setFormData(prev => ({ ...prev, repo: e.target.value }))}
                required
              />
            </div>
            <div className="form-group">
              <label className="filter-label">Issue #</label>
              <input
                type="number"
                className="form-input"
                placeholder="e.g. 5432"
                value={formData.issueNumber}
                onChange={e => setFormData(prev => ({ ...prev, issueNumber: e.target.value }))}
                required
              />
            </div>
          </div>
          <div className="form-row">
            <div className="form-group" style={{ flex: 1 }}>
              <label className="filter-label">Issue Title (optional)</label>
              <input
                type="text"
                className="form-input"
                placeholder="Brief description of the issue"
                value={formData.issueTitle}
                onChange={e => setFormData(prev => ({ ...prev, issueTitle: e.target.value }))}
              />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="filter-label">Issue URL (optional)</label>
              <input
                type="text"
                className="form-input"
                placeholder="https://github.com/owner/repo/issues/123"
                value={formData.issueUrl}
                onChange={e => setFormData(prev => ({ ...prev, issueUrl: e.target.value }))}
              />
            </div>
          </div>
          <button type="submit" className="btn btn--primary" disabled={assigning}>
            {assigning ? 'Forking & Assigning...' : 'Fork & Assign'}
          </button>
        </form>
      </div>

      <hr className="stage-divider" />

      {/* Assignments Table */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            <span className="stage-section__icon">{'\u{2705}'}</span>
            Active Assignments ({assignments.length})
          </h3>
        </div>

        {assignments.length === 0 ? (
          <EmptyState
            icon="\u{1F4ED}"
            title="No active assignments"
            description="Use the form above to fork a repo and assign an issue to Copilot."
          />
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Origin Repo</th>
                  <th>Issue #</th>
                  <th>Fork Issue</th>
                  <th>Assigned</th>
                </tr>
              </thead>
              <tbody>
                {assignments.map((a: OSSAssignment) => (
                  <tr key={`${a.originSlug}-${a.issueNumber}`}>
                    <td>
                      <span className="repo-link">{a.originSlug}</span>
                    </td>
                    <td className="text-light">#{a.issueNumber}</td>
                    <td>
                      <a
                        href={a.forkIssueUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="issue-link"
                      >
                        Fork #{a.forkIssueNumber}
                      </a>
                    </td>
                    <td className="text-light">{formatTimeAgo(a.assignedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
