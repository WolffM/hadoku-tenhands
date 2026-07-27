/**
 * Stage1Install
 *
 * Install VibeCheck on repos that don't have it.
 */

import { usePipelineStore } from '../../store'
import { installVibecheck } from '../../api/endpoints'
import { useBatchAction } from '../../hooks'
import type { Stage1Repo } from '../../api/types'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'

export function Stage1Install() {
  const stage1 = usePipelineStore(state => state.stage1)
  const owner = usePipelineStore(state => state.owner)
  const removeStage1Repo = usePipelineStore(state => state.removeStage1Repo)

  const repos = stage1.items

  const {
    processing,
    selectedCount,
    toggleItem,
    selectAll,
    selectNone,
    isSelected,
    processSelected
  } = useBatchAction<Stage1Repo>({
    processItem: async repo => {
      if (!owner) return { success: false, error: 'No owner' }
      const result = await installVibecheck(owner, repo.name)
      return { success: result.success, error: result.error }
    },
    getItemId: repo => repo.name,
    getItemName: repo => repo.name,
    onItemSuccess: repo => removeStage1Repo(repo.name),
    actionVerb: 'Installed'
  })

  // Loading state
  if (stage1.loading && repos.length === 0) {
    return <LoadingState text="Loading repos..." />
  }

  // Empty state - all repos have vibecheck
  if (repos.length === 0) {
    return (
      <EmptyState
        icon="✅"
        title="All repos have VibeCheck installed!"
        description="There are no repos that need VibeCheck installed."
      />
    )
  }

  return (
    <div className="stage-panel">
      <div className="stage-panel__header">
        <div className="stage-panel__actions">
          <button className="btn btn--secondary btn--sm" onClick={() => selectAll(repos)}>
            Select All
          </button>
          <button className="btn btn--secondary btn--sm" onClick={selectNone}>
            Select None
          </button>
          <button
            className="btn btn--primary btn--sm"
            onClick={() => {
              void processSelected(repos)
            }}
            disabled={processing || selectedCount === 0}
          >
            {processing ? 'Installing...' : `Install Selected (${selectedCount})`}
          </button>
        </div>
      </div>

      <div className="repo-grid">
        {repos.map(repo => (
          <RepoCheckbox
            key={repo.name}
            repo={repo}
            checked={isSelected(repo)}
            onChange={() => toggleItem(repo)}
            disabled={processing}
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
