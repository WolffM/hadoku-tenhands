/**
 * RepoFilterPopover
 *
 * Compact popover-style filter for OSS repos. Shows a trigger button
 * with count indicator; clicking opens a dropdown with search, All/None
 * bulk actions, and a scrollable checkbox list. Filter state is global
 * (Zustand store) and applies across all OSS tabs.
 */

import { useState, useRef, useEffect, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { usePipelineStore, selectAllOSSRepos } from '../../store'

export function RepoFilterPopover() {
  const allRepos = usePipelineStore(useShallow(selectAllOSSRepos))
  const excludedRepos = usePipelineStore(state => state.ossExcludedRepos)
  const toggleOSSRepoFilter = usePipelineStore(state => state.toggleOSSRepoFilter)
  const setOSSRepoFilterAll = usePipelineStore(state => state.setOSSRepoFilterAll)
  const setOSSRepoFilterNone = usePipelineStore(state => state.setOSSRepoFilterNone)

  const [isOpen, setIsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const panelRef = useRef<HTMLDivElement>(null)

  // Click-outside-to-close
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen])

  const visibleCount = allRepos.length - excludedRepos.size
  const totalCount = allRepos.length

  const filteredRepos = useMemo(() => {
    if (!searchQuery.trim()) return allRepos
    const q = searchQuery.toLowerCase()
    return allRepos.filter(r => r.toLowerCase().includes(q))
  }, [allRepos, searchQuery])

  if (totalCount === 0) return null

  return (
    <div className="repo-filter-popover" ref={panelRef}>
      <button
        className="btn btn--secondary btn--sm repo-filter-trigger"
        onClick={() => setIsOpen(prev => !prev)}
      >
        Repos ({visibleCount} of {totalCount})
      </button>

      {isOpen && (
        <div className="repo-filter-popover__panel">
          <div className="repo-filter-popover__search">
            <input
              type="text"
              placeholder="Search projects..."
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              autoFocus
            />
          </div>

          <div className="repo-filter-popover__actions">
            <button className="btn btn--secondary btn--sm" onClick={() => setOSSRepoFilterAll()}>
              All
            </button>
            <button
              className="btn btn--secondary btn--sm"
              onClick={() => setOSSRepoFilterNone(allRepos)}
            >
              None
            </button>
          </div>

          <div className="repo-filter-popover__list">
            {filteredRepos.map(repo => (
              <label key={repo} className="repo-filter-popover__item">
                <input
                  type="checkbox"
                  checked={!excludedRepos.has(repo)}
                  onChange={() => toggleOSSRepoFilter(repo)}
                />
                <span>{repo}</span>
              </label>
            ))}
            {filteredRepos.length === 0 && (
              <div className="repo-filter-popover__empty">No matches</div>
            )}
          </div>

          <div className="repo-filter-popover__footer">
            {visibleCount} of {totalCount} selected
          </div>
        </div>
      )}
    </div>
  )
}
