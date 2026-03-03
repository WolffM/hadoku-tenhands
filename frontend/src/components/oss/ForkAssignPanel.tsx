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
import { Badge, CVS_TIER_VARIANT } from '../common/Badge'
import { SectionHeader } from '../common/SectionHeader'
import { FilterBar, type FilterDefinition } from '../common/FilterBar'
import { BatchActionBar } from '../common/BatchActionBar'
import { OSSDossierPanel } from './OSSDossierPanel'

export function ForkAssignPanel() {
  const ossStage2 = usePipelineStore(state => state.ossStage2)
  const loadOSSPipelineRuns = usePipelineStore(state => state.loadOSSPipelineRuns)

  const excludedRepos = usePipelineStore(state => state.ossExcludedRepos)

  // Filter state
  const [tierFilter, setTierFilter] = useState<string>('all')
  const [complexityFilter, setComplexityFilter] = useState<string>('all')
  const [lifecycleFilter, setLifecycleFilter] = useState<string>('all')

  // Dossier panel state
  const [dossierSlug, setDossierSlug] = useState<string | null>(null)

  // Pagination for All Issues table (avoids rendering 8000+ rows)
  const PAGE_SIZE = 50
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  // Filter + sort logic
  const filteredIssues = useMemo(() => {
    let issues = [...ossStage2.items]
    // Global repo filter
    issues = issues.filter(i => !excludedRepos.has(i.repo))
    if (tierFilter !== 'all') issues = issues.filter(i => i.cvsTier === tierFilter)
    if (complexityFilter !== 'all') issues = issues.filter(i => i.complexity === complexityFilter)
    if (lifecycleFilter !== 'all') issues = issues.filter(i => i.lifecycleStage === lifecycleFilter)
    issues.sort((a, b) => b.cvs - a.cvs)
    return issues
  }, [ossStage2.items, excludedRepos, tierFilter, complexityFilter, lifecycleFilter])

  // Reset pagination when filters change
  const filteredCount = filteredIssues.length
  const [prevFilteredCount, setPrevFilteredCount] = useState(filteredCount)
  if (filteredCount !== prevFilteredCount) {
    setPrevFilteredCount(filteredCount)
    setVisibleCount(PAGE_SIZE)
  }

  // Top 5 recommended issues (highest CVS from filtered repos)
  const recommended = useMemo(() => {
    return filteredIssues.filter(i => i.cvsTier === 'go' || i.cvsTier === 'likely').slice(0, 5)
  }, [filteredIssues])

  // Paginated slice for the All Issues table
  const visibleIssues = useMemo(() => {
    return filteredIssues.slice(0, visibleCount)
  }, [filteredIssues, visibleCount])

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
      void loadOSSPipelineRuns()
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
          description="Add target repos in Repo Health first — issues will appear here once scored."
        />
      </div>
    )
  }

  return (
    <div className="stage-panel">
      {/* Recommended Section */}
      {recommended.length > 0 && (
        <div className="stage-section">
          <SectionHeader icon={'\u2B50'} title="Recommended" count={recommended.length}>
            <BatchActionBar
              onSelectAll={() => selectAll(recommended)}
              onSelectNone={selectNone}
              onProcess={() => {
                void processSelected(recommended)
              }}
              selectedCount={selectedCount}
              processLabel="Assign Selected"
              processing={assigning}
            />
          </SectionHeader>
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
                </tr>
              </thead>
              <tbody>
                {recommended.map(issue => (
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
                        {issue.title.length > 60
                          ? issue.title.substring(0, 60) + '...'
                          : issue.title}
                      </a>
                    </td>
                    <td>
                      <strong>{issue.cvs}</strong>
                    </td>
                    <td>
                      <Badge variant={CVS_TIER_VARIANT[issue.cvsTier] ?? 'secondary'}>
                        {issue.cvsTier}
                      </Badge>
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
      <FilterBar
        filters={
          [
            {
              label: 'CVS Tier',
              value: tierFilter,
              onChange: setTierFilter,
              options: [
                { value: 'all', label: 'All Tiers' },
                { value: 'go', label: 'Go' },
                { value: 'likely', label: 'Likely' },
                { value: 'maybe', label: 'Maybe' },
                { value: 'risky', label: 'Risky' }
              ]
            },
            {
              label: 'Complexity',
              value: complexityFilter,
              onChange: setComplexityFilter,
              options: [
                { value: 'all', label: 'All' },
                { value: 'low', label: 'Low' },
                { value: 'medium', label: 'Medium' },
                { value: 'high', label: 'High' }
              ]
            },
            {
              label: 'Lifecycle',
              value: lifecycleFilter,
              onChange: setLifecycleFilter,
              options: [
                { value: 'all', label: 'All' },
                { value: 'fresh', label: 'Fresh' },
                { value: 'triaged', label: 'Triaged' },
                { value: 'accepted', label: 'Accepted' },
                { value: 'stale', label: 'Stale' }
              ]
            }
          ] satisfies FilterDefinition[]
        }
      />

      {/* Issues Table */}
      <div className="stage-section">
        <SectionHeader icon={'\u{1F4CB}'} title="All Issues" count={filteredIssues.length} />

        {filteredIssues.length === 0 ? (
          <EmptyState
            icon="\u{1F50D}"
            title="No matching issues"
            description="Try adjusting your filters or enabling more repos."
          />
        ) : (
          <>
            <div className="table-container">
              <table className="data-table">
                <thead>
                  <tr>
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
                  {visibleIssues.map((issue: ScoredIssue) => {
                    const displayTitle =
                      issue.title.length > 50 ? issue.title.substring(0, 50) + '...' : issue.title

                    return (
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
                            {displayTitle}
                          </a>
                          {issue.dataCompleteness === 'partial' && (
                            <span
                              className="badge badge--secondary"
                              style={{ marginLeft: '0.5rem' }}
                            >
                              partial
                            </span>
                          )}
                        </td>
                        <td>
                          <strong>{issue.cvs}</strong>
                        </td>
                        <td>
                          <Badge variant={CVS_TIER_VARIANT[issue.cvsTier] ?? 'secondary'}>
                            {issue.cvsTier}
                          </Badge>
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
            {visibleCount < filteredIssues.length && (
              <div style={{ textAlign: 'center', padding: '1rem' }}>
                <button
                  className="btn btn--secondary btn--sm"
                  onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
                >
                  Show More ({filteredIssues.length - visibleCount} remaining)
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Dossier Side Panel */}
      {dossierSlug && <OSSDossierPanel slug={dossierSlug} onClose={() => setDossierSlug(null)} />}
    </div>
  )
}
