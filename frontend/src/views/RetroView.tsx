/**
 * RetroView — batch retrospective page.
 *
 * Tab strip:
 *   - Legacy   → existing oss-contribution batches (default tab)
 *   - Temporal → crimson-kitty batches from the Temporal pipeline
 *
 * Each tab is lazy: the Temporal tab does not fetch until selected.
 */

import { useState, useEffect } from 'react'
import { getRetroBatches, getRetroBatchDetail } from '../api/endpoints'
import type { BatchSummary, BatchIssue } from '../api/types'
import { BatchSummaryPanel } from '../components/retro/BatchSummaryPanel'
import { IssueRetroCard } from '../components/retro/IssueRetroCard'
import { LoadingState } from '../components/common'
import { useTemporalStore } from '../store/temporalStore'
import { StateBadge } from '../components/temporal'

const MAX_VISIBLE_TABS = 5

type RetroTab = 'legacy' | 'temporal'

export function RetroView() {
  const [activeTab, setActiveTab] = useState<RetroTab>('legacy')

  return (
    <div className="retro-view" data-testid="retro-view">
      <div className="retro-view__tab-strip" data-testid="retro-tab-strip">
        <button
          type="button"
          data-testid="retro-tab-legacy"
          className={`retro-view__tab ${activeTab === 'legacy' ? 'retro-view__tab--active' : ''}`}
          onClick={() => setActiveTab('legacy')}
        >
          Legacy
        </button>
        <button
          type="button"
          data-testid="retro-tab-temporal"
          className={`retro-view__tab ${activeTab === 'temporal' ? 'retro-view__tab--active' : ''}`}
          onClick={() => setActiveTab('temporal')}
        >
          Temporal
        </button>
      </div>
      {activeTab === 'legacy' ? <LegacyRetroTab /> : <TemporalRetroTab />}
    </div>
  )
}

// ── Legacy tab: prior behavior, unchanged ────────────────────────────────

function LegacyRetroTab() {
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
          const sorted = [...res.batches].sort(
            (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )
          setBatches(sorted)
          if (sorted.length > 0) {
            setActiveBatchId(prev => prev ?? sorted[0].batch_id)
          }
        }
      })
      .catch((err: unknown) =>
        setError(`Failed to load batches: ${err instanceof Error ? err.message : String(err)}`)
      )
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
          const summary = batches.find(b => b.batch_id === activeBatchId)
          setActiveBatch(summary ?? null)
        } else {
          setError(res.error ?? 'Failed to load batch')
        }
      })
      .catch((err: unknown) =>
        setError(`Failed to load batch detail: ${err instanceof Error ? err.message : String(err)}`)
      )
      .finally(() => setLoadingIssues(false))
  }, [activeBatchId, batches])

  if (loadingBatches) return <LoadingState text="Loading batches…" />
  if (error) return <div className="retro-error">{error}</div>

  const visibleTabs = batches.slice(0, MAX_VISIBLE_TABS)
  const olderBatches = batches.slice(MAX_VISIBLE_TABS)

  return (
    <div data-testid="retro-tab-content-legacy">
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

      {activeBatch && <BatchSummaryPanel batch={activeBatch} />}

      <div className="retro-issue-list">
        {loadingIssues ? (
          <LoadingState text="Loading issues…" />
        ) : issues.length === 0 ? (
          <div className="retro-empty">No issues in this batch yet.</div>
        ) : (
          issues.map((item, i) => <IssueRetroCard key={i} item={item} />)
        )}
      </div>
    </div>
  )
}

// ── Temporal tab: crimson-kitty batches, lazy ────────────────────────────

function TemporalRetroTab() {
  const batches = useTemporalStore(s => s.batches)
  const batchDetail = useTemporalStore(s => s.batchDetail)
  const loadBatches = useTemporalStore(s => s.loadBatches)
  const loadBatch = useTemporalStore(s => s.loadBatch)

  useEffect(() => {
    void loadBatches()
  }, [loadBatches])

  if (batches.loading && batches.items.length === 0) {
    return <LoadingState text="Loading temporal batches…" />
  }
  if (batches.error) {
    return (
      <div className="retro-error" data-testid="retro-temporal-error">
        {batches.error}
      </div>
    )
  }

  return (
    <div data-testid="retro-tab-content-temporal">
      <div className="retro-tabs">
        {batches.items.length === 0 ? (
          <p data-testid="retro-temporal-empty">No temporal batches yet.</p>
        ) : (
          batches.items.map(b => (
            <button
              key={b.batch_id}
              type="button"
              data-testid="retro-temporal-batch-button"
              className="retro-tab"
              onClick={() => {
                void loadBatch(b.batch_id)
              }}
            >
              {b.batch_id} ({b.issue_count})
            </button>
          ))
        )}
      </div>

      {batchDetail.loading && <LoadingState text="Loading batch…" />}
      {batchDetail.data && (
        <div className="retro-issue-list" data-testid="retro-temporal-issues">
          <h3>{batchDetail.data.batch_id}</h3>
          <ul>
            {batchDetail.data.issues.map(i => (
              <li key={i.issue_id} data-testid="retro-temporal-issue">
                <span>{i.issue_id}</span> <StateBadge state={i.current_state} />{' '}
                <span>
                  {i.transition_count} transitions · {i.gate_count} gates
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
