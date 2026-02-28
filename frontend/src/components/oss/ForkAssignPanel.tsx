/**
 * ForkAssignPanel — Tab 2
 *
 * Combines repo filtering, recommended top-5 issues, and the full scored issues
 * table with batch fork-and-assign support.
 */

import { useState, useMemo } from 'react'
import { usePipelineStore } from '../../store'
import { selectOSSIssue, forkAndAssign } from '../../api/endpoints'
import { useBatchAction } from '../../hooks'
import type { ScoredIssue } from '../../api/types'
import { formatTimeAgo } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'
import { OSSDossierPanel } from './OSSDossierPanel'

const TIER_BADGE_CLASS: Record<string, string> = {
  go: 'badge--success',
  likely: 'badge--primary',
  maybe: 'badge--warning',
  risky: 'badge--danger',
  skip: 'badge--secondary'
}

export function ForkAssignPanel() {
  const ossStage2 = usePipelineStore(state => state.ossStage2)
  const loadOSSPipelineRuns = usePipelineStore(state => state.loadOSSPipelineRuns)

  // Filter state
  const [tierFilter, setTierFilter] = useState<string>('all')
  const [complexityFilter, setComplexityFilter] = useState<string>('all')
  const [lifecycleFilter, setLifecycleFilter] = useState<string>('all')

  // Repo filter state
  const [enabledRepos, setEnabledRepos] = useState<Set<string> | null>(null)

  // Dossier panel state
  const [dossierSlug, setDossierSlug] = useState<string | null>(null)

  // Unique repos from scored issues
  const allRepos = useMemo(() => {
    const repos = new Set<string>()
    for (const issue of ossStage2.items) {
      if (issue.repo) repos.add(issue.repo)
    }
    return Array.from(repos).sort()
  }, [ossStage2.items])

  // Initialize enabledRepos to all repos on first render
  const activeRepos = enabledRepos ?? new Set(allRepos)

  const toggleRepo = (repo: string) => {
    const next = new Set(activeRepos)
    if (next.has(repo)) {
      next.delete(repo)
    } else {
      next.add(repo)
    }
    setEnabledRepos(next)
  }

  // Filter + sort logic
  const filteredIssues = useMemo(() => {
    let issues = [...ossStage2.items]
    // Repo filter
    issues = issues.filter(i => activeRepos.has(i.repo))
    if (tierFilter !== 'all') issues = issues.filter(i => i.cvsTier === tierFilter)
    if (complexityFilter !== 'all') issues = issues.filter(i => i.complexity === complexityFilter)
    if (lifecycleFilter !== 'all') issues = issues.filter(i => i.lifecycleStage === lifecycleFilter)
    issues.sort((a, b) => b.cvs - a.cvs)
    return issues
  }, [ossStage2.items, activeRepos, tierFilter, complexityFilter, lifecycleFilter])

  // Top 5 recommended issues (highest CVS from filtered repos)
  const recommended = useMemo(() => {
    return filteredIssues.filter(i => i.cvsTier === 'go' || i.cvsTier === 'likely').slice(0, 5)
  }, [filteredIssues])

  // Batch fork-and-assign
  const {
    processing: assigning,
    selectedCount,
    toggleItem,
    selectAll,
    selectNone,
    isSelected,
    processSelected,
    processSingle
  } = useBatchAction<ScoredIssue>({
    processItem: async issue => {
      const parts = issue.repo.split('/')
      if (parts.length !== 2) return { success: false, error: 'Invalid repo format' }
      const [originOwner, repo] = parts
      await selectOSSIssue(originOwner, repo, issue.number, issue.title, issue.url)
      const result = await forkAndAssign(originOwner, repo, issue.number, issue.title, issue.url)
      return { success: result.success, error: result.error }
    },
    getItemId: issue => issue.id,
    getItemName: issue => `${issue.repo}#${issue.number}`,
    onItemSuccess: () => {
      void loadOSSPipelineRuns()
    },
    actionVerb: 'Assigned'
  })

  const handleAssignRecommended = async () => {
    if (recommended.length === 0) return
    for (const issue of recommended) {
      await processSingle(issue)
    }
  }

  const handleViewDossier = (issue: ScoredIssue) => {
    setDossierSlug(issue.repo.replace('/', '-'))
  }

  if (ossStage2.loading && ossStage2.items.length === 0) {
    return <LoadingState text="Loading scored issues..." />
  }

  if (ossStage2.items.length === 0) {
    return (
      <div className="stage-panel">
        <EmptyState
          icon="\u{1F4CB}"
          title="No scored issues"
          description="Add target repos in Repo Health first — issues will appear here once scored."
        />
      </div>
    )
  }

  return (
    <div className="stage-panel">
      {/* Repo Filter */}
      {allRepos.length > 1 && (
        <div className="stage-section">
          <div className="stage-section__header">
            <h3 className="stage-section__title">
              <span className="stage-section__icon">{'\u{1F50D}'}</span>
              Filter by Repo
            </h3>
          </div>
          <div className="repo-filter">
            {allRepos.map(repo => (
              <label key={repo} className="repo-filter__item">
                <input
                  type="checkbox"
                  checked={activeRepos.has(repo)}
                  onChange={() => toggleRepo(repo)}
                />
                <span>{repo}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Recommended Section */}
      {recommended.length > 0 && (
        <div className="stage-section">
          <div className="stage-section__header">
            <h3 className="stage-section__title">
              <span className="stage-section__icon">{'\u2B50'}</span>
              Recommended ({recommended.length})
            </h3>
            <button
              className="btn btn--primary btn--sm"
              onClick={() => {
                void handleAssignRecommended()
              }}
              disabled={assigning}
            >
              {assigning ? 'Assigning...' : 'Assign All Recommended'}
            </button>
          </div>
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Repo</th>
                  <th>#</th>
                  <th>Title</th>
                  <th>CVS</th>
                  <th>Tier</th>
                </tr>
              </thead>
              <tbody>
                {recommended.map(issue => (
                  <tr key={issue.id}>
                    <td>
                      <span className="repo-link">{issue.repo}</span>
                    </td>
                    <td className="text-light">#{issue.number}</td>
                    <td>
                      <a
                        href={issue.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="issue-link"
                        title={issue.title}
                      >
                        {issue.title.length > 60
                          ? issue.title.substring(0, 60) + '...'
                          : issue.title}
                      </a>
                    </td>
                    <td>
                      <strong>{issue.cvs}</strong>
                    </td>
                    <td>
                      <span
                        className={`badge ${TIER_BADGE_CLASS[issue.cvsTier] || 'badge--secondary'}`}
                      >
                        {issue.cvsTier}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <hr className="stage-divider" />

      {/* Filter Bar */}
      <div className="filter-bar">
        <div className="filter-group">
          <label className="filter-label">CVS Tier</label>
          <select
            className="filter-select"
            value={tierFilter}
            onChange={e => setTierFilter(e.target.value)}
          >
            <option value="all">All Tiers</option>
            <option value="go">Go</option>
            <option value="likely">Likely</option>
            <option value="maybe">Maybe</option>
            <option value="risky">Risky</option>
          </select>
        </div>
        <div className="filter-group">
          <label className="filter-label">Complexity</label>
          <select
            className="filter-select"
            value={complexityFilter}
            onChange={e => setComplexityFilter(e.target.value)}
          >
            <option value="all">All</option>
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
          </select>
        </div>
        <div className="filter-group">
          <label className="filter-label">Lifecycle</label>
          <select
            className="filter-select"
            value={lifecycleFilter}
            onChange={e => setLifecycleFilter(e.target.value)}
          >
            <option value="all">All</option>
            <option value="fresh">Fresh</option>
            <option value="triaged">Triaged</option>
            <option value="accepted">Accepted</option>
            <option value="stale">Stale</option>
          </select>
        </div>
      </div>

      {/* Issues Table */}
      <div className="stage-section">
        <div className="stage-section__header">
          <h3 className="stage-section__title">
            <span className="stage-section__icon">{'\u{1F4CB}'}</span>
            All Issues ({filteredIssues.length})
          </h3>
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
          <EmptyState
            icon="\u{1F50D}"
            title="No matching issues"
            description="Try adjusting your filters or enabling more repos."
          />
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '30px' }}></th>
                  <th>Repo</th>
                  <th>#</th>
                  <th>Title</th>
                  <th>CVS</th>
                  <th>Tier</th>
                  <th>Labels</th>
                  <th>Comments</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredIssues.map((issue: ScoredIssue) => {
                  const displayTitle =
                    issue.title.length > 50 ? issue.title.substring(0, 50) + '...' : issue.title

                  return (
                    <tr key={issue.id}>
                      <td>
                        <input
                          type="checkbox"
                          className="checkbox"
                          checked={isSelected(issue)}
                          onChange={() => toggleItem(issue)}
                          disabled={assigning}
                        />
                      </td>
                      <td>
                        <span className="repo-link">{issue.repo}</span>
                      </td>
                      <td className="text-light">#{issue.number}</td>
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
                        {issue.dataCompleteness === 'partial' && (
                          <span className="badge badge--secondary" style={{ marginLeft: '0.5rem' }}>
                            partial
                          </span>
                        )}
                      </td>
                      <td>
                        <strong>{issue.cvs}</strong>
                      </td>
                      <td>
                        <span
                          className={`badge ${TIER_BADGE_CLASS[issue.cvsTier] || 'badge--secondary'}`}
                        >
                          {issue.cvsTier}
                        </span>
                      </td>
                      <td className="text-light">
                        {issue.labels.slice(0, 3).join(', ')}
                        {issue.labels.length > 3 && ` +${issue.labels.length - 3}`}
                      </td>
                      <td className="text-light">{issue.commentCount}</td>
                      <td className="text-light">{formatTimeAgo(issue.createdAt)}</td>
                      <td>
                        <button
                          className="btn btn--secondary btn--sm"
                          onClick={() => handleViewDossier(issue)}
                        >
                          Dossier
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Dossier Side Panel */}
      {dossierSlug && <OSSDossierPanel slug={dossierSlug} onClose={() => setDossierSlug(null)} />}
    </div>
  )
}
