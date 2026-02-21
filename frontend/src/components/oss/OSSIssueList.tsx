/**
 * OSSIssueList — Stage 2
 *
 * Browse scored issues across all target repos.
 * Filter by CVS tier, complexity, lifecycle.
 * Batch select issues for work (flows to Stage 3 fork-and-assign).
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

export function OSSIssueList() {
  const ossStage2 = usePipelineStore(state => state.ossStage2)
  const loadOSSStage3 = usePipelineStore(state => state.loadOSSStage3)

  // Filter state
  const [tierFilter, setTierFilter] = useState<string>('all')
  const [complexityFilter, setComplexityFilter] = useState<string>('all')
  const [lifecycleFilter, setLifecycleFilter] = useState<string>('all')

  // Dossier panel state
  const [dossierSlug, setDossierSlug] = useState<string | null>(null)

  // Filter + sort logic
  const filteredIssues = useMemo(() => {
    let issues = [...ossStage2.items]
    if (tierFilter !== 'all') issues = issues.filter(i => i.cvsTier === tierFilter)
    if (complexityFilter !== 'all') issues = issues.filter(i => i.complexity === complexityFilter)
    if (lifecycleFilter !== 'all') issues = issues.filter(i => i.lifecycleStage === lifecycleFilter)
    issues.sort((a, b) => b.cvs - a.cvs)
    return issues
  }, [ossStage2.items, tierFilter, complexityFilter, lifecycleFilter])

  // Batch fork-and-assign
  const {
    processing: assigning,
    selectedCount,
    toggleItem,
    selectAll,
    selectNone,
    isSelected,
    processSelected
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
      void loadOSSStage3()
    },
    actionVerb: 'Assigned'
  })

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
          description="Add target repos in Stage 1 first — issues will appear here once fetched."
        />
      </div>
    )
  }

  return (
    <div className="stage-panel">
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
            <option value="go">Go ({'\u{2705}'})</option>
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
            Scored Issues ({filteredIssues.length})
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
            description="Try adjusting your filters."
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
