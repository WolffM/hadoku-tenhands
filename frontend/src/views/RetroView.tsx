/**
 * RetroView — batch retrospective page.
 *
 * Batch tabs (last 5 + Older dropdown), BatchSummaryPanel funnel,
 * and per-issue IssueRetroCards.
 */

import { useState, useEffect } from 'react'
import { getRetroBatches, getRetroBatchDetail } from '../api/endpoints'
import type { BatchSummary, BatchIssue } from '../api/types'
import { BatchSummaryPanel } from '../components/retro/BatchSummaryPanel'
import { IssueRetroCard } from '../components/retro/IssueRetroCard'
import { LoadingState } from '../components/common'

const MAX_VISIBLE_TABS = 5

export function RetroView() {
  const [batches, setBatches] = useState<BatchSummary[]>([])
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)
  const [issues, setIssues] = useState<BatchIssue[]>([])
  const [activeBatch, setActiveBatch] = useState<BatchSummary | null>(null)
  const [loadingBatches, setLoadingBatches] = useState(true)
  const [loadingIssues, setLoadingIssues] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [olderOpen, setOlderOpen] = useState(false)

  useEffect(() => {
    setLoadingBatches(true)
    getRetroBatches()
      .then(res => {
        if (res.success && res.batches) {
          // Sort newest first
          const sorted = [...res.batches].sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )
          setBatches(sorted)
          if (sorted.length > 0 && !activeBatchId) {
            setActiveBatchId(sorted[0].batch_id)
          }
        }
      })
      .catch(() => setError('Failed to load batches'))
      .finally(() => setLoadingBatches(false))
  }, [])

  useEffect(() => {
    if (!activeBatchId) return
    setLoadingIssues(true)
    setIssues([])
    getRetroBatchDetail(activeBatchId)
      .then(res => {
        if (res.success) {
          setIssues(res.issues ?? [])
          setActiveBatch(res.batch ?? null)
        } else {
          setError(res.error ?? 'Failed to load batch')
        }
      })
      .catch(() => setError('Failed to load batch detail'))
      .finally(() => setLoadingIssues(false))
  }, [activeBatchId])

  if (loadingBatches) return <LoadingState message="Loading batches…" />
  if (error) return <div className="retro-error">{error}</div>

  const visibleTabs = batches.slice(0, MAX_VISIBLE_TABS)
  const olderBatches = batches.slice(MAX_VISIBLE_TABS)

  return (
    <div className="retro-view">
      {/* Batch tabs */}
      <div className="retro-tabs">
        {visibleTabs.map(b => (
          <button
            key={b.batch_id}
            className={`retro-tab ${activeBatchId === b.batch_id ? 'retro-tab--active' : ''}`}
            onClick={() => setActiveBatchId(b.batch_id)}
          >
            {b.batch_id}
            {b.upstream_merged > 0 && (
              <span className="retro-tab__badge">{b.upstream_merged} merged</span>
            )}
          </button>
        ))}
        {olderBatches.length > 0 && (
          <div className="retro-tabs__older">
            <button className="retro-tab retro-tab--older" onClick={() => setOlderOpen(v => !v)}>
              Older ▾
            </button>
            {olderOpen && (
              <div className="retro-tabs__dropdown">
                {olderBatches.map(b => (
                  <button
                    key={b.batch_id}
                    className={`retro-tabs__dropdown-item ${activeBatchId === b.batch_id ? 'retro-tabs__dropdown-item--active' : ''}`}
                    onClick={() => {
                      setActiveBatchId(b.batch_id)
                      setOlderOpen(false)
                    }}
                  >
                    {b.batch_id}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Batch summary funnel */}
      {activeBatch && <BatchSummaryPanel batch={activeBatch} />}

      {/* Issue list */}
      <div className="retro-issue-list">
        {loadingIssues ? (
          <LoadingState message="Loading issues…" />
        ) : issues.length === 0 ? (
          <div className="retro-empty">No issues in this batch yet.</div>
        ) : (
          issues.map((item, i) => <IssueRetroCard key={i} item={item} />)
        )}
      </div>
    </div>
  )
}
