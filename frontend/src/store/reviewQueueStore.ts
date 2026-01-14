/**
 * Review Queue Store
 *
 * State management for the review carousel/queue.
 */

import { create } from 'zustand'
import type { PRDetails, PipelineItem, PullRequest } from '../api/types'
import { getPRDetails } from '../api/endpoints'

// ============ Types ============

export interface ReviewQueueState {
  // Queue of items awaiting review
  queue: PipelineItem[]

  // Current index in the queue
  currentIndex: number

  // Currently viewed item details (e.g., PR with diff)
  currentDetails: PRDetails | null
  detailsLoading: boolean
  detailsError: string | null

  // Actions
  setQueue: (items: PipelineItem[]) => void
  goToNext: () => void
  goToPrevious: () => void
  goToIndex: (index: number) => void
  loadCurrentDetails: (owner: string) => Promise<void>
  clearDetails: () => void
  removeCurrentFromQueue: () => void
}

// ============ Store ============

export const useReviewQueueStore = create<ReviewQueueState>((set, get) => ({
  queue: [],
  currentIndex: 0,
  currentDetails: null,
  detailsLoading: false,
  detailsError: null,

  setQueue: items => {
    set({
      queue: items,
      currentIndex: 0,
      currentDetails: null,
      detailsError: null
    })
  },

  goToNext: () => {
    const { queue, currentIndex } = get()
    if (currentIndex < queue.length - 1) {
      set({
        currentIndex: currentIndex + 1,
        currentDetails: null,
        detailsError: null
      })
    }
  },

  goToPrevious: () => {
    const { currentIndex } = get()
    if (currentIndex > 0) {
      set({
        currentIndex: currentIndex - 1,
        currentDetails: null,
        detailsError: null
      })
    }
  },

  goToIndex: index => {
    const { queue } = get()
    if (index >= 0 && index < queue.length) {
      set({
        currentIndex: index,
        currentDetails: null,
        detailsError: null
      })
    }
  },

  loadCurrentDetails: async owner => {
    const { queue, currentIndex } = get()
    const currentItem = queue[currentIndex]

    if (!currentItem) {
      set({ detailsError: 'No item selected' })
      return
    }

    // Currently only handles PR details
    if (!currentItem.id.startsWith('pr-')) {
      // For non-PR items, just use the existing data
      set({ currentDetails: null, detailsLoading: false })
      return
    }

    // Extract PR info from the pipeline item
    const pr = currentItem.data as PullRequest
    if (!pr || !pr.number) {
      set({ detailsError: 'Invalid PR data' })
      return
    }

    set({ detailsLoading: true, detailsError: null })

    try {
      const response = await getPRDetails(owner, currentItem.repo, pr.number)
      if (response.success && response.pr) {
        set({
          currentDetails: response.pr,
          detailsLoading: false
        })
      } else {
        set({
          detailsError: response.error || 'Failed to load PR details',
          detailsLoading: false
        })
      }
    } catch (err) {
      set({
        detailsError: err instanceof Error ? err.message : 'Unknown error',
        detailsLoading: false
      })
    }
  },

  clearDetails: () => {
    set({
      currentDetails: null,
      detailsError: null
    })
  },

  removeCurrentFromQueue: () => {
    const { queue, currentIndex } = get()
    if (queue.length === 0) return

    const newQueue = [...queue]
    newQueue.splice(currentIndex, 1)

    // Adjust index if we removed the last item
    const newIndex = Math.min(currentIndex, newQueue.length - 1)

    set({
      queue: newQueue,
      currentIndex: Math.max(0, newIndex),
      currentDetails: null,
      detailsError: null
    })
  }
}))

// ============ Selectors ============
// NOTE: Selectors must return primitive values or stable references.
// Returning new objects/arrays causes infinite re-renders in React 18+.

export const selectCurrentItem = (state: ReviewQueueState) =>
  state.queue[state.currentIndex] || null

// Split position into two primitive selectors to avoid creating new objects
export const selectQueueCurrentIndex = (state: ReviewQueueState) => state.currentIndex + 1

export const selectQueueTotal = (state: ReviewQueueState) => state.queue.length

export const selectHasNext = (state: ReviewQueueState) =>
  state.currentIndex < state.queue.length - 1

export const selectHasPrevious = (state: ReviewQueueState) => state.currentIndex > 0

export const selectIsQueueEmpty = (state: ReviewQueueState) => state.queue.length === 0
