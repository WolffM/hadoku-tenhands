/**
 * OSSView
 *
 * Main view for the 4-tab OSS contribution pipeline.
 * Tab 1: Repo Health — dossier sections, health scores, scrape/compute actions
 * Tab 2: Fork & Assign — repo filter, recommended issues, batch assign
 * Tab 3: Pipeline Runs — progress bars, report detail, signoff
 * Tab 4: Review — production PR command center
 */

import { useEffect, useRef } from 'react'
import { usePipelineStore, selectIsOSSLoading } from '../store'
import { hyphenatedToSlashed } from '../utils'
import { RepoHealthPanel } from '../components/oss/RepoHealthPanel'
import { ForkAssignPanel } from '../components/oss/ForkAssignPanel'
import { PipelineRunsPanel } from '../components/oss/PipelineRunsPanel'
import { ProductionReviewPanel } from '../components/oss/ProductionReviewPanel'
import { RepoFilterPopover } from '../components/oss/RepoFilterPopover'
import { ProgressLog, StageTabView, type StageTabConfig } from '../components/common'

export function OSSView() {
  const isLoading = usePipelineStore(selectIsOSSLoading)
  const loadAllOSSStages = usePipelineStore(state => state.loadAllOSSStages)

  const ossStage1 = usePipelineStore(state => state.ossStage1)
  const ossStage2 = usePipelineStore(state => state.ossStage2)
  const ossPipelineRuns = usePipelineStore(state => state.ossPipelineRuns)
  const ossSubmittedPRs = usePipelineStore(state => state.ossSubmittedPRs)
  const excludedRepos = usePipelineStore(state => state.ossExcludedRepos)

  // Load all OSS stages on mount
  const initialLoadDoneRef = useRef(false)
  useEffect(() => {
    if (initialLoadDoneRef.current) return
    initialLoadDoneRef.current = true
    void loadAllOSSStages()
  }, [loadAllOSSStages])

  const stages: StageTabConfig[] = [
    {
      id: 'health',
      label: 'Repo Health',
      icon: 'hospital',
      component: RepoHealthPanel,
      getCount: () =>
        ossStage1.items.filter(
          t => !excludedRepos.has(hyphenatedToSlashed((t as { slug: string }).slug ?? ''))
        ).length
    },
    {
      id: 'assign',
      label: 'Fork & Assign',
      icon: 'layers',
      component: ForkAssignPanel,
      getCount: () =>
        ossStage2.items.filter(i => !excludedRepos.has((i as { repo: string }).repo)).length
    },
    {
      id: 'pipeline',
      label: 'Pipeline Runs',
      icon: 'gear',
      component: PipelineRunsPanel,
      getCount: () =>
        ossPipelineRuns.items.filter(
          a => !excludedRepos.has((a as { originSlug: string }).originSlug)
        ).length
    },
    {
      id: 'review',
      label: 'Review',
      icon: 'chart',
      component: ProductionReviewPanel,
      getCount: () =>
        ossSubmittedPRs.items.filter(
          p => !excludedRepos.has((p as { originSlug: string }).originSlug)
        ).length
    }
  ]

  return (
    <div className="oss-view">
      <StageTabView
        stages={stages}
        isLoading={isLoading}
        onRefreshAll={() => {
          void loadAllOSSStages()
        }}
        defaultStageId="pipeline"
        extraActions={<RepoFilterPopover />}
      />
      <ProgressLog />
    </div>
  )
}
