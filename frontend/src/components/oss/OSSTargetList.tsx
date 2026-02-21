/**
 * OSSTargetList — Stage 1
 *
 * Add/remove target repos for the OSS contribution pipeline.
 * Shows repos with health scores (aggregator) or basic metadata (gh CLI fallback).
 */

import { useState, type FormEvent } from 'react'
import { usePipelineStore } from '../../store'
import { addOSSTarget, removeOSSTarget, refreshOSSTarget } from '../../api/endpoints'
import type { OSSTarget } from '../../api/types'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'

function HealthBadge({ score }: { score: number }) {
  const cls = score > 70 ? 'badge--success' : score >= 40 ? 'badge--warning' : 'badge--danger'
  return <span className={`badge ${cls}`}>{score}</span>
}

export function OSSTargetList() {
  const ossStage1 = usePipelineStore(state => state.ossStage1)
  const loadOSSStage1 = usePipelineStore(state => state.loadOSSStage1)
  const loadOSSStage2 = usePipelineStore(state => state.loadOSSStage2)
  const addLog = usePipelineStore(state => state.addLog)

  const [newSlug, setNewSlug] = useState('')
  const [adding, setAdding] = useState(false)
  const [removingSlug, setRemovingSlug] = useState<string | null>(null)
  const [refreshingSlug, setRefreshingSlug] = useState<string | null>(null)

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault()
    const slug = newSlug.trim()
    if (!slug || !slug.includes('/')) return

    setAdding(true)
    addLog(`Adding target: ${slug}...`, 'info')

    try {
      const result = await addOSSTarget(slug)
      if (result.success) {
        addLog(`Added target: ${slug}`, 'success')
        setNewSlug('')
        void loadOSSStage1()
        void loadOSSStage2()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to add target', 'error')
    } finally {
      setAdding(false)
    }
  }

  const handleRemove = async (target: OSSTarget) => {
    setRemovingSlug(target.slug)
    addLog(`Removing target: ${target.slug}...`, 'info')

    try {
      const result = await removeOSSTarget(target.slug)
      if (result.success) {
        addLog(`Removed target: ${target.slug}`, 'success')
        void loadOSSStage1()
        void loadOSSStage2()
      } else {
        addLog(`Failed: ${result.error}`, 'error')
      }
    } catch {
      addLog('Failed to remove target', 'error')
    } finally {
      setRemovingSlug(null)
    }
  }

  const handleRefresh = async (target: OSSTarget) => {
    setRefreshingSlug(target.slug)
    addLog(`Refreshing target: ${target.slug}...`, 'info')

    try {
      const result = await refreshOSSTarget(target.slug)
      if (result.success) {
        addLog(`Refreshed: ${target.slug}`, 'success')
        void loadOSSStage1()
        void loadOSSStage2()
      }
    } catch {
      addLog('Failed to refresh target', 'error')
    } finally {
      setRefreshingSlug(null)
    }
  }

  const targets = ossStage1.items

  if (ossStage1.loading && targets.length === 0) {
    return <LoadingState text="Loading targets..." />
  }

  return (
    <div className="stage-panel">
      {/* Add Target Form */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            <span className="stage-section__icon">{'\u{1F3AF}'}</span>
            Add Target Repo
          </h3>
        </div>

        <form
          onSubmit={e => {
            void handleAdd(e)
          }}
          className="oss-add-target-form"
        >
          <div className="form-group" style={{ flex: 1 }}>
            <label className="filter-label">Repository (owner/repo)</label>
            <input
              type="text"
              className="form-input"
              placeholder="e.g. fastify/fastify"
              value={newSlug}
              onChange={e => setNewSlug(e.target.value)}
              required
            />
          </div>
          <button
            type="submit"
            className="btn btn--primary"
            disabled={adding || !newSlug.includes('/')}
          >
            {adding ? 'Adding...' : 'Add Target'}
          </button>
        </form>
      </div>

      <hr className="stage-divider" />

      {/* Targets Table */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            <span className="stage-section__icon">{'\u{1F4CB}'}</span>
            Watchlist ({targets.length})
          </h3>
        </div>

        {targets.length === 0 ? (
          <EmptyState
            icon="\u{1F4ED}"
            title="No target repos"
            description="Use the form above to add repos you want to contribute to."
          />
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Repository</th>
                  <th>Health</th>
                  <th>Language</th>
                  <th>Stars</th>
                  <th>Open Issues</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {targets.map((target: OSSTarget) => (
                  <tr key={target.slug}>
                    <td>
                      <span className="repo-link">{target.slug}</span>
                    </td>
                    <td>
                      {target.health ? (
                        <HealthBadge score={target.health.overallViability} />
                      ) : (
                        <span className="badge badge--secondary">N/A</span>
                      )}
                    </td>
                    <td className="text-light">{target.meta?.language || '—'}</td>
                    <td className="text-light">
                      {target.meta?.stars !== null && target.meta?.stars !== undefined
                        ? target.meta.stars.toLocaleString()
                        : '—'}
                    </td>
                    <td className="text-light">
                      {target.meta?.openIssueCount !== null &&
                      target.meta?.openIssueCount !== undefined
                        ? target.meta.openIssueCount
                        : '—'}
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button
                          className="btn btn--secondary btn--sm"
                          onClick={() => {
                            void handleRefresh(target)
                          }}
                          disabled={refreshingSlug === target.slug}
                        >
                          {refreshingSlug === target.slug ? '...' : 'Refresh'}
                        </button>
                        <button
                          className="btn btn--danger btn--sm"
                          onClick={() => {
                            void handleRemove(target)
                          }}
                          disabled={removingSlug === target.slug}
                        >
                          {removingSlug === target.slug ? '...' : 'Remove'}
                        </button>
                      </div>
                    </td>
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
