/**
 * TemporalPipelineView — main view for the crimson-kitty pipeline.
 *
 * Three tabs:
 *   - Inbox   — the operator action queue (deferred workflows). Default.
 *   - Active  — batches that still have inbox items, browsable run-by-run.
 *   - Archive — batches with nothing pending.
 *
 * The inbox lives on its own tab so the operator never scrolls past it to
 * reach a run, and batch browsing is a separate side-by-side layout with
 * the first batch + first run auto-selected.
 *
 * Uses `useTemporalStore` exclusively.
 */

import { useEffect, useRef, useState } from 'react'
import { useTemporalStore } from '../store/temporalStore'
import { PipelineInbox, BatchBrowser } from '../components/temporal'

type TabKey = 'inbox' | 'active' | 'archive'

export function TemporalPipelineView() {
  const batches = useTemporalStore(s => s.batches)
  const inbox = useTemporalStore(s => s.inbox)
  const selectedBatchId = useTemporalStore(s => s.selectedBatchId)
  const loadBatches = useTemporalStore(s => s.loadBatches)
  const loadInbox = useTemporalStore(s => s.loadInbox)

  const [tab, setTab] = useState<TabKey>('inbox')
  const deepLinkHandled = useRef(false)

  useEffect(() => {
    void loadBatches()
    void loadInbox()
  }, [loadBatches, loadInbox])

  const activeBatches = batches.items.filter(b => b.active)
  const archiveBatches = batches.items.filter(b => !b.active)

  // Deep links (?view=temporal&batch=…) pre-select a batch in App.tsx. Once
  // the batch list first loads, jump to the tab that holds the pre-selected
  // batch so the selection is visible instead of stranded behind the default
  // Inbox tab. Guarded by a ref so it runs exactly once and never fights a
  // later manual tab click.
  useEffect(() => {
    if (deepLinkHandled.current || batches.items.length === 0) return
    deepLinkHandled.current = true
    if (!selectedBatchId) return
    if (activeBatches.some(b => b.batch_id === selectedBatchId)) setTab('active')
    else if (archiveBatches.some(b => b.batch_id === selectedBatchId)) setTab('archive')
  }, [batches.items.length, selectedBatchId, activeBatches, archiveBatches])

  const tabs: { key: TabKey; label: string; count: number }[] = [
    { key: 'inbox', label: 'Inbox', count: inbox.items.length },
    { key: 'active', label: 'Active', count: activeBatches.length },
    { key: 'archive', label: 'Archive', count: archiveBatches.length }
  ]

  return (
    <div className="temporal-pipeline-view" data-testid="temporal-pipeline-view">
      <nav className="temporal-tabs" data-testid="temporal-tabs">
        {tabs.map(t => (
          <button
            key={t.key}
            type="button"
            className="temporal-tabs__tab"
            data-testid={`temporal-tab-${t.key}`}
            data-active={tab === t.key}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            <span className="temporal-tabs__count">{t.count}</span>
          </button>
        ))}
      </nav>

      <div className="temporal-pipeline-view__body">
        {tab === 'inbox' && <PipelineInbox />}
        {tab === 'active' && (
          <BatchBrowser
            batches={activeBatches}
            emptyText="No active batches — the inbox is clear."
          />
        )}
        {tab === 'archive' && (
          <BatchBrowser batches={archiveBatches} emptyText="No archived batches yet." />
        )}
      </div>
    </div>
  )
}
