/**
 * Stage1Install
 *
 * Install VibeCheck on repos that don't have it.
 */

import { useState } from 'react'
import { usePipelineStore } from '../../store'
import { batchInstallVibecheck } from '../../api/endpoints'
import type { Stage1Repo } from '../../api/types'

export function Stage1Install() {
  const stage1 = usePipelineStore(state => state.stage1)
  const owner = usePipelineStore(state => state.owner)
  const loadStage1 = usePipelineStore(state => state.loadStage1)
  const addLog = usePipelineStore(state => state.addLog)

  const [selectedRepos, setSelectedRepos] = useState<Set<string>>(new Set())
  const [installing, setInstalling] = useState(false)

  const repos = stage1.items

  const toggleRepo = (repoName: string) => {
    setSelectedRepos(prev => {
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
    setSelectedRepos(new Set(repos.map(r => r.name)))
  }

  const selectNone = () => {
    setSelectedRepos(new Set())
  }

  const installSelected = async () => {
    if (!owner || selectedRepos.size === 0) return

    setInstalling(true)
    addLog(`Installing VibeCheck on ${selectedRepos.size} repos...`, 'info')

    const repoList = Array.from(selectedRepos)
    let successCount = 0

    await batchInstallVibecheck(owner, repoList, (completed, total, result) => {
      if (result.success) {
        successCount++
        addLog(`Installed on ${result.repo}`, 'success')
      } else {
        addLog(`Failed on ${result.repo}: ${result.error}`, 'error')
      }
    })

    addLog(
      `Done! Installed on ${successCount}/${repoList.length} repos`,
      successCount > 0 ? 'success' : 'error'
    )
    setInstalling(false)
    setSelectedRepos(new Set())

    // Reload after a delay
    setTimeout(() => {
      void loadStage1()
    }, 1000)
  }

  // Loading state
  if (stage1.loading && repos.length === 0) {
    return (
      <div className="loading-state">
        <div className="loading-state__spinner" />
        <p className="loading-state__text">Loading repos...</p>
      </div>
    )
  }

  // Empty state - all repos have vibecheck
  if (repos.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">✅</div>
        <h3 className="empty-state__title">All repos have VibeCheck installed!</h3>
        <p className="empty-state__description">
          There are no repos that need VibeCheck installed.
        </p>
      </div>
    )
  }

  return (
    <div className="stage-panel">
      <div className="stage-panel__header">
        <div className="stage-panel__actions">
          <button className="btn btn--secondary btn--sm" onClick={selectAll}>
            Select All
          </button>
          <button className="btn btn--secondary btn--sm" onClick={selectNone}>
            Select None
          </button>
          <button
            className="btn btn--primary btn--sm"
            onClick={() => {
              void installSelected()
            }}
            disabled={installing || selectedRepos.size === 0}
          >
            {installing ? 'Installing...' : `Install Selected (${selectedRepos.size})`}
          </button>
        </div>
      </div>

      <div className="repo-grid">
        {repos.map(repo => (
          <RepoCheckbox
            key={repo.name}
            repo={repo}
            checked={selectedRepos.has(repo.name)}
            onChange={() => toggleRepo(repo.name)}
            disabled={installing}
          />
        ))}
      </div>
    </div>
  )
}

interface RepoCheckboxProps {
  repo: Stage1Repo
  checked: boolean
  onChange: () => void
  disabled: boolean
}

function RepoCheckbox({ repo, checked, onChange, disabled }: RepoCheckboxProps) {
  return (
    <label className={`repo-checkbox ${disabled ? 'repo-checkbox--disabled' : ''}`}>
      <input type="checkbox" checked={checked} onChange={onChange} disabled={disabled} />
      <span className="repo-checkbox__name">{repo.name}</span>
      {repo.isPrivate && <span className="repo-checkbox__private">🔒</span>}
    </label>
  )
}
