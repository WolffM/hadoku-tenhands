/**
 * Stage2Run
 *
 * Run VibeCheck on repos that have it installed.
 * Shows recommended repos (needs run) and all repos.
 */

import { useState, useEffect, useRef } from 'react'
import { usePipelineStore } from '../../store'
import { batchRunVibecheck, runVibecheck, batchUpdateVibecheck } from '../../api/endpoints'
import type { Stage2Repo } from '../../api/types'
import { formatTimeAgo } from '../../utils'

export function Stage2Run() {
  const stage2 = usePipelineStore(state => state.stage2)
  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const markStage2RepoTriggered = usePipelineStore(state => state.markStage2RepoTriggered)

  const [selectedRepos, setSelectedRepos] = useState<Set<string>>(new Set())
  const [selectedRecommended, setSelectedRecommended] = useState<Set<string>>(new Set())
  const [running, setRunning] = useState(false)
  const [updating, setUpdating] = useState(false)

  // Track if we've initialized the selection
  const initializedRef = useRef(false)

  const repos = stage2.items

  // Split repos into recommended (needs run) and others
  const recommended = repos.filter(repo => {
    const lastRun = repo.lastRun
    const status = (lastRun ? lastRun.conclusion || lastRun.status : 'none') as string
    const isRunning = ['in_progress', 'queued', 'triggered'].includes(status)
    const needsRun = !lastRun || repo.commitsSinceLastRun > 0
    return needsRun && !isRunning
  })

  const others = repos.filter(repo => !recommended.includes(repo))

  // Initialize recommended selection - select all recommended by default
  useEffect(() => {
    if (recommended.length > 0 && !initializedRef.current) {
      setSelectedRecommended(new Set(recommended.map(r => r.name)))
      initializedRef.current = true
    }
  }, [recommended])

  const toggleRepo = (repoName: string, isRecommended: boolean) => {
    const setter = isRecommended ? setSelectedRecommended : setSelectedRepos
    setter(prev => {
      const next = new Set(prev)
      if (next.has(repoName)) {
        next.delete(repoName)
      } else {
        next.add(repoName)
      }
      return next
    })
  }

  const selectAll = () => {
    setSelectedRepos(new Set(others.map(r => r.name)))
  }

  const selectNone = () => {
    setSelectedRepos(new Set())
  }

  const runAllRecommended = async () => {
    if (!owner || selectedRecommended.size === 0) return

    setRunning(true)
    addLog(`Running VibeCheck on ${selectedRecommended.size} recommended repos...`, 'info')

    const repoList = Array.from(selectedRecommended)
    let successCount = 0

    await batchRunVibecheck(owner, repoList, (completed, total, result) => {
      if (result.success) {
        successCount++
        addLog(`Triggered on ${result.repo}`, 'success')
        // Immediately update UI - mark repo as triggered so it moves out of recommended
        markStage2RepoTriggered(result.repo)
        setSelectedRecommended(prev => {
          const next = new Set(prev)
          next.delete(result.repo)
          return next
        })
      } else {
        addLog(`Failed on ${result.repo}: ${result.error}`, 'error')
      }
    })

    addLog(
      `All workflows triggered! (${successCount}/${repoList.length} successful)`,
      successCount > 0 ? 'success' : 'error'
    )
    setRunning(false)
  }

  const runSelected = async () => {
    if (!owner || selectedRepos.size === 0) return

    setRunning(true)
    addLog(`Running VibeCheck on ${selectedRepos.size} repos...`, 'info')

    const repoList = Array.from(selectedRepos)
    let successCount = 0

    await batchRunVibecheck(owner, repoList, (completed, total, result) => {
      if (result.success) {
        successCount++
        addLog(`Triggered on ${result.repo}`, 'success')
        // Immediately update UI - mark repo as triggered
        markStage2RepoTriggered(result.repo)
        setSelectedRepos(prev => {
          const next = new Set(prev)
          next.delete(result.repo)
          return next
        })
      } else {
        addLog(`Failed on ${result.repo}: ${result.error}`, 'error')
      }
    })

    addLog(
      `All workflows triggered! (${successCount}/${repoList.length} successful)`,
      successCount > 0 ? 'success' : 'error'
    )
    setRunning(false)
  }

  const updateAllWorkflows = async () => {
    if (!owner || repos.length === 0) return

    setUpdating(true)
    addLog(`Updating vibecheck workflows on ${repos.length} repos to latest version...`, 'info')

    const repoList = repos.map(r => r.name)
    let successCount = 0

    await batchUpdateVibecheck(owner, repoList, (completed, total, result) => {
      if (result.success) {
        successCount++
        addLog(`Updated ${result.repo}`, 'success')
      } else {
        addLog(`Failed to update ${result.repo}: ${result.error}`, 'error')
      }
    })

    addLog(
      `Workflow update complete! (${successCount}/${repoList.length} successful)`,
      successCount > 0 ? 'success' : 'error'
    )
    setUpdating(false)
  }

  const runSingle = async (repo: Stage2Repo) => {
    if (!owner) return

    addLog(`Running VibeCheck on ${repo.name}...`, 'info')

    try {
      const result = await runVibecheck(owner, repo.name)
      if (result.success) {
        addLog(`Triggered on ${repo.name}`, 'success')
        // Immediately update UI
        markStage2RepoTriggered(repo.name)
        setSelectedRecommended(prev => {
          const next = new Set(prev)
          next.delete(repo.name)
          return next
        })
        setSelectedRepos(prev => {
          const next = new Set(prev)
          next.delete(repo.name)
          return next
        })
      } else {
        addLog(`Failed on ${repo.name}: ${result.error}`, 'error')
      }
    } catch {
      addLog(`Failed on ${repo.name}`, 'error')
    }
  }

  // Loading state
  if (stage2.loading && repos.length === 0) {
    return (
      <div className="loading-state">
        <div className="loading-state__spinner" />
        <p className="loading-state__text">Loading repos with commit info...</p>
      </div>
    )
  }

  // Empty state
  if (repos.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">📭</div>
        <h3 className="empty-state__title">No repos with VibeCheck installed</h3>
        <p className="empty-state__description">Install VibeCheck on repos in Stage 1 first.</p>
      </div>
    )
  }

  return (
    <div className="stage-panel">
      {/* Global Actions */}
      <div className="stage-panel__header" style={{ marginBottom: '1rem' }}>
        <div className="stage-panel__actions">
          <button
            className="btn btn--secondary btn--sm"
            onClick={() => {
              void updateAllWorkflows()
            }}
            disabled={updating || running || repos.length === 0}
            title="Update all repos to latest vibecheck workflow from WolffM/vibecheck"
          >
            {updating ? 'Updating...' : `🔄 Refresh Workflows (${repos.length})`}
          </button>
        </div>
      </div>

      {/* Recommended Section */}
      {recommended.length > 0 && (
        <div className="stage-section stage-section--recommended">
          <div className="stage-section__header">
            <h3 className="stage-section__title">
              <span className="stage-section__icon">⭐</span>
              Recommended ({recommended.length} repos need VibeCheck)
            </h3>
            <button
              className="btn btn--primary btn--sm"
              onClick={() => {
                void runAllRecommended()
              }}
              disabled={running || selectedRecommended.size === 0}
            >
              ▶️ Run Selected ({selectedRecommended.size})
            </button>
          </div>

          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '30px' }}></th>
                  <th>Repository</th>
                  <th>Last Run</th>
                  <th>Commits Since</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {recommended.map(repo => (
                  <RecommendedRow
                    key={repo.name}
                    repo={repo}
                    checked={selectedRecommended.has(repo.name)}
                    onChange={() => toggleRepo(repo.name, true)}
                    onRun={() => {
                      void runSingle(repo)
                    }}
                    disabled={running}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Divider */}
      {recommended.length > 0 && others.length > 0 && <hr className="stage-divider" />}

      {/* All Repos / Other Repos Section */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            {recommended.length > 0 ? 'Other Repos' : 'All Repos'}
          </h3>
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
                void runSelected()
              }}
              disabled={running || selectedRepos.size === 0}
            >
              Run Selected ({selectedRepos.size})
            </button>
          </div>
        </div>

        <div className="table-container">
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: '30px' }}></th>
                <th>Repository</th>
                <th>Last Run</th>
                <th>Status</th>
                <th>Commits Since</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {(recommended.length > 0 ? others : repos).map(repo => (
                <RepoRow
                  key={repo.name}
                  repo={repo}
                  checked={selectedRepos.has(repo.name)}
                  onChange={() => toggleRepo(repo.name, false)}
                  onRun={() => {
                    void runSingle(repo)
                  }}
                  disabled={running}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

interface RecommendedRowProps {
  repo: Stage2Repo
  checked: boolean
  onChange: () => void
  onRun: () => void
  disabled: boolean
}

function RecommendedRow({ repo, checked, onChange, onRun, disabled }: RecommendedRowProps) {
  const lastRunTime = repo.lastRun ? formatTimeAgo(repo.lastRun.createdAt) : 'Never'
  const commits = repo.commitsSinceLastRun

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
        <span className="repo-link">{repo.name}</span>
      </td>
      <td className="text-secondary">{lastRunTime}</td>
      <td>
        {commits > 0 ? (
          <span className="badge badge--warning">{commits} new</span>
        ) : (
          <span className="text-secondary">Never run</span>
        )}
      </td>
      <td>
        <button
          className="btn btn--ghost btn--sm"
          onClick={onRun}
          disabled={disabled}
          title="Run VibeCheck"
        >
          ▶️
        </button>
      </td>
    </tr>
  )
}

interface RepoRowProps {
  repo: Stage2Repo
  checked: boolean
  onChange: () => void
  onRun: () => void
  disabled: boolean
}

function RepoRow({ repo, checked, onChange, onRun, disabled }: RepoRowProps) {
  const lastRun = repo.lastRun
  const lastRunTime = lastRun ? formatTimeAgo(lastRun.createdAt) : 'Never'
  const status = (lastRun ? lastRun.conclusion || lastRun.status : 'none') as string
  const commits = repo.commitsSinceLastRun
  const needsRun = !lastRun || commits > 0
  const isRunning = ['in_progress', 'queued', 'triggered'].includes(status)
  const canRun = needsRun && !isRunning

  return (
    <tr>
      <td>
        <input
          type="checkbox"
          className="checkbox"
          checked={checked}
          onChange={onChange}
          disabled={disabled || !canRun}
        />
      </td>
      <td>
        <span className="repo-link">{repo.name}</span>
      </td>
      <td className="text-secondary">{lastRunTime}</td>
      <td>
        <StatusBadge status={status} />
      </td>
      <td>
        {commits > 0 ? (
          <span className="badge badge--warning">{commits} new</span>
        ) : (
          <span className="text-secondary">0</span>
        )}
      </td>
      <td>
        <button
          className="btn btn--ghost btn--sm"
          onClick={onRun}
          disabled={disabled || !canRun}
          title={!canRun ? (isRunning ? 'Already running' : 'No new commits') : 'Run VibeCheck'}
        >
          {isRunning ? '🔄' : '▶️'}
        </button>
      </td>
    </tr>
  )
}

function StatusBadge({ status }: { status: string }) {
  const getClass = () => {
    switch (status) {
      case 'success':
        return 'badge--success'
      case 'failure':
        return 'badge--danger'
      case 'in_progress':
      case 'queued':
      case 'triggered':
        return 'badge--info'
      default:
        return 'badge--secondary'
    }
  }

  return <span className={`badge ${getClass()}`}>{status}</span>
}
