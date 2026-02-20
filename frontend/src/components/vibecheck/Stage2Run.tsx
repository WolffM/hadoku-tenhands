/**
 * Stage2Run
 *
 * Run VibeCheck on repos that have it installed.
 * Shows recommended repos (needs run) and all repos.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { runVibecheck, batchUpdateVibecheck } from '../../api/endpoints'
import { useBatchAction } from '../../hooks'
import type { Stage2Repo } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'

export function Stage2Run() {
  const stage2 = usePipelineStore(state => state.stage2)
  const owner = usePipelineStore(state => state.owner)
  const addLog = usePipelineStore(state => state.addLog)
  const markStage2RepoTriggered = usePipelineStore(state => state.markStage2RepoTriggered)

  const [updating, setUpdating] = useState(false)

  const repos = stage2.items

  // Split repos into recommended (needs run) and others
  const recommended = useMemo(
    () =>
      repos.filter(repo => {
        const lastRun = repo.lastRun
        const status = (lastRun ? lastRun.conclusion || lastRun.status : 'none') as string
        const isRunning = ['in_progress', 'queued', 'triggered'].includes(status)
        const needsRun = !lastRun || repo.commitsSinceLastRun > 0
        return needsRun && !isRunning
      }),
    [repos]
  )

  const others = useMemo(
    () => repos.filter(repo => !recommended.includes(repo)),
    [repos, recommended]
  )

  // Batch action for running vibecheck
  const {
    processing: running,
    selectedCount,
    toggleItem,
    selectAll,
    selectNone,
    isSelected,
    processSelected,
    processSingle
  } = useBatchAction<Stage2Repo>({
    processItem: async repo => {
      if (!owner) return { success: false, error: 'No owner' }
      const result = await runVibecheck(owner, repo.name)
      return { success: result.success, error: result.error }
    },
    getItemId: repo => repo.name,
    getItemName: repo => repo.name,
    onItemSuccess: repo => markStage2RepoTriggered(repo.name),
    actionVerb: 'Triggered'
  })

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

  // Loading state
  if (stage2.loading && repos.length === 0) {
    return <LoadingState text="Loading repos with commit info..." />
  }

  // Empty state
  if (repos.length === 0) {
    return (
      <EmptyState
        icon="📭"
        title="No repos with VibeCheck installed"
        description="Install VibeCheck on repos in Stage 1 first."
      />
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
            <div className="stage-section__actions">
              <button className="btn btn--secondary btn--sm" onClick={() => selectAll(recommended)}>
                Select All
              </button>
              <button
                className="btn btn--primary btn--sm"
                onClick={() => {
                  void processSelected(recommended)
                }}
                disabled={running || updating || selectedCount === 0}
              >
                ▶️ Run Selected ({selectedCount})
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
                  <th>Commits Since</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {recommended.map(repo => (
                  <RecommendedRow
                    key={repo.name}
                    repo={repo}
                    checked={isSelected(repo)}
                    onChange={() => toggleItem(repo)}
                    onRun={() => {
                      void processSingle(repo)
                    }}
                    disabled={running || updating}
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
            <button className="btn btn--secondary btn--sm" onClick={() => selectAll(others)}>
              Select All
            </button>
            <button className="btn btn--secondary btn--sm" onClick={selectNone}>
              Select None
            </button>
            <button
              className="btn btn--primary btn--sm"
              onClick={() => {
                void processSelected(others)
              }}
              disabled={running || updating || selectedCount === 0}
            >
              Run Selected ({selectedCount})
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
                  checked={isSelected(repo)}
                  onChange={() => toggleItem(repo)}
                  onRun={() => {
                    void processSingle(repo)
                  }}
                  disabled={running || updating}
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
