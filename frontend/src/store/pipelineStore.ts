/**
 * Pipeline Store
 *
 * Central state management using Zustand.
 * Composed from focused slice modules — state shape is identical to before.
 */

import { create } from 'zustand'
import type { RepoHealthTarget } from '../api/types'
import { hyphenatedToSlashed } from '../utils'
import { createVibeCheckSlice, type VibeCheckSliceState } from './vibeCheckStore'
import { createOSSSlice, type OSSSliceState } from './ossStore'
import { createUISlice, type UISliceState } from './uiStore'
import { createFilterSlice, type FilterSliceState } from './filterStore'

// Re-export types that consumers import from this module
export type { ViewType, LogEntry } from './uiStore'

// ============ Combined State ============

interface PipelineState extends VibeCheckSliceState, OSSSliceState, UISliceState, FilterSliceState {}

// ============ Store ============

export const usePipelineStore = create<PipelineState>((set, get) => ({
  ...createVibeCheckSlice<PipelineState>(set, get),
  ...createOSSSlice<PipelineState>(set, get),
  ...createUISlice<PipelineState>(set, get),
  ...createFilterSlice<PipelineState>(set, get)
}))

// ============ Selectors ============

export const selectIsLoading = (state: PipelineState) =>
  state.stage1.loading || state.stage2.loading || state.stage3.loading || state.stage4.loading

export const selectIsOSSLoading = (state: PipelineState) =>
  state.ossStage1.loading ||
  state.ossStage2.loading ||
  state.ossPipelineRuns.loading ||
  state.ossRetrospectiveLogs.loading ||
  state.ossSubmittedPRs.loading

export function selectAllOSSRepos(state: PipelineState): string[] {
  const repos = new Set<string>()
  for (const t of state.ossStage1.items) {
    const slug = (t as RepoHealthTarget).slug
    if (slug) repos.add(hyphenatedToSlashed(slug))
  }
  for (const i of state.ossStage2.items) {
    if (i.repo) repos.add(i.repo)
  }
  for (const a of state.ossPipelineRuns.items) {
    if (a.originSlug) repos.add(a.originSlug)
  }
  for (const p of state.ossSubmittedPRs.items) {
    if (p.originSlug) repos.add(p.originSlug)
  }
  return Array.from(repos).sort()
}
