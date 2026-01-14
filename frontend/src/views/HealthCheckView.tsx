/**
 * HealthCheckView
 *
 * View for monitoring workflow health across repos.
 * Includes stats cards, filters, and workflow runs table.
 */

import { useEffect, useState, useMemo } from 'react'
import { getGlobalWorkflowRuns, getHealthCheck } from '../api/endpoints'
import type { WorkflowRun, HealthCheckResponse } from '../api/types'
import { formatTimeAgo } from '../utils'

interface WorkflowRunWithRepo extends WorkflowRun {
  repo: string
  vibecheck_installed: boolean
}

type VCFilter = 'all' | 'vc-installed' | 'vc-not-installed'
type StatusFilter = 'all' | 'success' | 'failure' | 'in_progress'

export function HealthCheckView() {
  const [health, setHealth] = useState<HealthCheckResponse | null>(null)
  const [allRuns, setAllRuns] = useState<WorkflowRunWithRepo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [vcFilter, setVcFilter] = useState<VCFilter>('all')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [workflowFilter, setWorkflowFilter] = useState('all')

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [healthResponse, runsResponse] = await Promise.all([
        getHealthCheck(),
        getGlobalWorkflowRuns()
      ])

      if (healthResponse.success) {
        setHealth(healthResponse)
      }

      if (runsResponse.success) {
        setAllRuns(runsResponse.runs as WorkflowRunWithRepo[])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadData()
  }, [])

  // Available workflow names for filter
  const workflowNames = useMemo(() => {
    return [...new Set(allRuns.map(r => r.workflowName || 'Unknown'))].sort()
  }, [allRuns])

  // Filter runs
  const filteredRuns = useMemo(() => {
    let filtered = allRuns

    if (vcFilter === 'vc-installed') {
      filtered = filtered.filter(r => r.vibecheck_installed)
    } else if (vcFilter === 'vc-not-installed') {
      filtered = filtered.filter(r => !r.vibecheck_installed)
    }

    if (statusFilter !== 'all') {
      filtered = filtered.filter(r => {
        const status = (r.conclusion || r.status || '').toLowerCase()
        return status === statusFilter
      })
    }

    if (workflowFilter !== 'all') {
      filtered = filtered.filter(r => r.workflowName === workflowFilter)
    }

    return filtered
  }, [allRuns, vcFilter, statusFilter, workflowFilter])

  // Stats
  const stats = useMemo(() => {
    return {
      total: filteredRuns.length,
      success: filteredRuns.filter(r => r.conclusion === 'success').length,
      failed: filteredRuns.filter(r => r.conclusion === 'failure').length,
      inProgress: filteredRuns.filter(r => r.status === 'in_progress').length
    }
  }, [filteredRuns])

  const showOnlyFailed = () => {
    setStatusFilter('failure')
  }

  const getStatusIcon = (run: WorkflowRun): string => {
    if (run.status === 'in_progress' || run.status === 'queued') {
      return '🔄'
    }
    if (run.conclusion === 'success') {
      return '✅'
    }
    if (run.conclusion === 'failure') {
      return '❌'
    }
    if (run.conclusion === 'cancelled') {
      return '⚪'
    }
    return '⏳'
  }

  const getStatusClass = (run: WorkflowRun): string => {
    if (run.conclusion === 'failure') {
      return 'table-row--danger'
    }
    return ''
  }

  return (
    <div className="health-view">
      {/* Header */}
      <div className="health-header">
        <div>
          <h2 className="health-title">Health Check</h2>
          <p className="health-subtitle">Monitor workflow status across all repositories</p>
        </div>
        <button
          className="btn btn--primary"
          onClick={() => {
            void loadData()
          }}
          disabled={loading}
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Stats Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <h6 className="stat-card__label">Total Runs</h6>
          <h2 className="stat-card__value">{stats.total}</h2>
        </div>
        <div className="stat-card">
          <h6 className="stat-card__label">Successful</h6>
          <h2 className="stat-card__value stat-card__value--success">{stats.success}</h2>
        </div>
        <div className="stat-card">
          <h6 className="stat-card__label">Failed</h6>
          <h2 className="stat-card__value stat-card__value--danger">{stats.failed}</h2>
        </div>
        <div className="stat-card">
          <h6 className="stat-card__label">In Progress</h6>
          <h2 className="stat-card__value stat-card__value--warning">{stats.inProgress}</h2>
        </div>
      </div>

      {/* Filters */}
      <div className="filter-card">
        <div className="filter-card__header">
          <span>🔍 Filters</span>
        </div>
        <div className="filter-card__body">
          <div className="filter-row">
            <div className="filter-group">
              <label className="filter-label">VibeCheck Status</label>
              <select
                className="filter-select"
                value={vcFilter}
                onChange={e => setVcFilter(e.target.value as VCFilter)}
              >
                <option value="all">All Repos</option>
                <option value="vc-installed">VC Installed</option>
                <option value="vc-not-installed">VC Not Installed</option>
              </select>
            </div>
            <div className="filter-group">
              <label className="filter-label">Run Status</label>
              <select
                className="filter-select"
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value as StatusFilter)}
              >
                <option value="all">All Status</option>
                <option value="success">Success</option>
                <option value="failure">Failed</option>
                <option value="in_progress">In Progress</option>
              </select>
            </div>
            <div className="filter-group">
              <label className="filter-label">Workflow Name</label>
              <select
                className="filter-select"
                value={workflowFilter}
                onChange={e => setWorkflowFilter(e.target.value)}
              >
                <option value="all">All Workflows</option>
                {workflowNames.map(name => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-group">
              <label className="filter-label">Quick Filters</label>
              <button className="btn btn--danger btn--sm" onClick={showOnlyFailed}>
                ⚠️ Show Failed
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* API Health Status */}
      {health && (
        <div className="health-status-card">
          <div className={`health-indicator health-indicator--${health.status}`}>
            {health.status === 'healthy' ? '✅' : '⚠️'} {health.status}
          </div>
          <div className="health-details">
            <span>Owner: {health.owner}</span>
            <span>API Version: {health.api_version}</span>
          </div>
        </div>
      )}

      {error && <div className="error-message">{error}</div>}

      {/* Workflow Runs Table */}
      <div className="workflow-card">
        <div className="workflow-card__header">
          <span>▶️ Recent Workflow Runs</span>
          <span className="badge badge--secondary">{filteredRuns.length}</span>
        </div>
        <div className="workflow-card__body">
          {loading && allRuns.length === 0 && (
            <div className="loading-state">
              <div className="loading-state__spinner" />
              <p className="loading-state__text">Loading workflow runs...</p>
            </div>
          )}

          {!loading && filteredRuns.length === 0 && (
            <p className="text-secondary text-center">No workflow runs found matching filters</p>
          )}

          {filteredRuns.length > 0 && (
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Repository</th>
                    <th>Workflow</th>
                    <th>Status</th>
                    <th>VC</th>
                    <th>Time</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRuns.map(run => (
                    <tr key={`${run.repo}-${run.id}`} className={getStatusClass(run)}>
                      <td>
                        <span className="repo-link">{run.repo}</span>
                      </td>
                      <td>{run.workflowName || 'Unknown'}</td>
                      <td>
                        <span
                          className={`badge ${
                            run.conclusion === 'success'
                              ? 'badge--success'
                              : run.conclusion === 'failure'
                                ? 'badge--danger'
                                : run.status === 'in_progress'
                                  ? 'badge--warning'
                                  : 'badge--secondary'
                          }`}
                        >
                          {getStatusIcon(run)} {run.conclusion || run.status || 'unknown'}
                        </span>
                      </td>
                      <td>
                        {run.vibecheck_installed ? (
                          <span title="VibeCheck installed">✅</span>
                        ) : (
                          <span title="VibeCheck not installed">➖</span>
                        )}
                      </td>
                      <td className="text-secondary">
                        {run.createdAt ? formatTimeAgo(run.createdAt) : '-'}
                      </td>
                      <td>
                        <a
                          href={
                            run.url || `https://github.com/${health?.owner}/${run.repo}/actions`
                          }
                          target="_blank"
                          rel="noopener noreferrer"
                          className="btn btn--ghost btn--sm"
                          title="View on GitHub"
                        >
                          🔗
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
