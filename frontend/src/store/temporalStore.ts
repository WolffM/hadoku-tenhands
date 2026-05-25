/**
 * Temporal (crimson-kitty) Store
 *
 * Standalone Zustand store for the crimson-kitty pipeline. Kept separate
 * from the composite `usePipelineStore` because the temporal pipeline has
 * its own data shape (batches / issues / inbox / evidence) that does not
 * fit the `PipelineItem` derivation model used by vibecheck + oss.
 *
 * Mirrors the async-action + error-handling pattern from `ossStore.ts`.
 */

import { create } from 'zustand'
import {
  getTemporalBatches,
  getTemporalBatch,
  getTemporalIssue,
  getTemporalInbox,
  sendTemporalSignal
} from '../api/endpoints'
import type {
  TemporalBatchSummary,
  TemporalBatchDetail,
  TemporalIssueDetail,
  TemporalInboxItem,
  TemporalSignalDecision,
  TemporalReasonCode
} from '../api/types'
import { getErrorMessage } from '../utils'

interface Slot<T> {
  data: T | null
  loading: boolean
  error: string | null
  lastFetched: Date | null
}

function emptySlot<T>(): Slot<T> {
  return { data: null, loading: false, error: null, lastFetched: null }
}

export interface TemporalState {
  batches: {
    items: TemporalBatchSummary[]
    loading: boolean
    error: string | null
    lastFetched: Date | null
  }
  batchDetail: Slot<TemporalBatchDetail>
  issueDetail: Slot<TemporalIssueDetail>
  inbox: {
    items: TemporalInboxItem[]
    loading: boolean
    error: string | null
    lastFetched: Date | null
  }

  selectedBatchId: string | null
  selectedIssueId: string | null

  loadBatches: () => Promise<void>
  loadBatch: (batchId: string) => Promise<void>
  loadIssue: (batchId: string, issueId: string) => Promise<void>
  loadInbox: () => Promise<void>
  sendSignal: (
    workflowId: string,
    decision: TemporalSignalDecision,
    options?: { reasonCode?: TemporalReasonCode | null; reasonText?: string }
  ) => Promise<void>
  selectBatch: (batchId: string | null) => void
  selectIssue: (issueId: string | null) => void
}

export const useTemporalStore = create<TemporalState>((set, get) => ({
  batches: { items: [], loading: false, error: null, lastFetched: null },
  batchDetail: emptySlot(),
  issueDetail: emptySlot(),
  inbox: { items: [], loading: false, error: null, lastFetched: null },
  selectedBatchId: null,
  selectedIssueId: null,

  loadBatches: async () => {
    set(s => ({ batches: { ...s.batches, loading: true, error: null } }))
    try {
      const items = await getTemporalBatches()
      set(s => ({
        batches: { ...s.batches, items, loading: false, lastFetched: new Date() }
      }))
    } catch (err) {
      set(s => ({ batches: { ...s.batches, loading: false, error: getErrorMessage(err) } }))
    }
  },

  loadBatch: async (batchId: string) => {
    set(s => ({ batchDetail: { ...s.batchDetail, loading: true, error: null } }))
    try {
      const data = await getTemporalBatch(batchId)
      set({
        batchDetail: { data, loading: false, error: null, lastFetched: new Date() },
        selectedBatchId: batchId
      })
    } catch (err) {
      set(s => ({
        batchDetail: { ...s.batchDetail, loading: false, error: getErrorMessage(err) }
      }))
    }
  },

  loadIssue: async (batchId: string, issueId: string) => {
    set(s => ({ issueDetail: { ...s.issueDetail, loading: true, error: null } }))
    try {
      const data = await getTemporalIssue(batchId, issueId)
      set({
        issueDetail: { data, loading: false, error: null, lastFetched: new Date() },
        selectedBatchId: batchId,
        selectedIssueId: issueId
      })
    } catch (err) {
      set(s => ({
        issueDetail: { ...s.issueDetail, loading: false, error: getErrorMessage(err) }
      }))
    }
  },

  loadInbox: async () => {
    set(s => ({ inbox: { ...s.inbox, loading: true, error: null } }))
    try {
      const { items } = await getTemporalInbox()
      set(s => ({
        inbox: { ...s.inbox, items, loading: false, lastFetched: new Date() }
      }))
    } catch (err) {
      set(s => ({ inbox: { ...s.inbox, loading: false, error: getErrorMessage(err) } }))
    }
  },

  sendSignal: async (
    workflowId: string,
    decision: TemporalSignalDecision,
    options?: { reasonCode?: TemporalReasonCode | null; reasonText?: string }
  ) => {
    await sendTemporalSignal(workflowId, decision, options)
    // Optimistically remove any inbox entry whose workflow_id matches.
    set(s => ({
      inbox: {
        ...s.inbox,
        items: s.inbox.items.filter(i => i.workflow_id !== workflowId)
      }
    }))
    // Refresh issue detail if the signaled workflow is currently selected.
    const sel = get().issueDetail.data
    if (sel && (sel as unknown as { workflow_id?: string }).workflow_id === workflowId) {
      const batchId = get().selectedBatchId
      const issueId = get().selectedIssueId
      if (batchId && issueId) {
        await get().loadIssue(batchId, issueId)
      }
    }
  },

  selectBatch: (batchId: string | null) => set({ selectedBatchId: batchId, selectedIssueId: null }),
  selectIssue: (issueId: string | null) => set({ selectedIssueId: issueId })
}))
