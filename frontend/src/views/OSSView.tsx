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
import { RepoHealthPanel } from '../components/oss/RepoHealthPanel'
import { ForkAssignPanel } from '../components/oss/ForkAssignPanel'
import { PipelineRunsPanel } from '../components/oss/PipelineRunsPanel'
import { ProductionReviewPanel } from '../components/oss/ProductionReviewPanel'
import { ProgressLog, StageTabView, type StageTabConfig } from '../components/common'

export function OSSView() {
  const isLoading = usePipelineStore(selectIsOSSLoading)
  const loadAllOSSStages = usePipelineStore(state => state.loadAllOSSStages)

  const ossStage1 = usePipelineStore(state => state.ossStage1)
  const ossStage2 = usePipelineStore(state => state.ossStage2)
  const ossPipelineRuns = usePipelineStore(state => state.ossPipelineRuns)
  const ossSubmittedPRs = usePipelineStore(state => state.ossSubmittedPRs)

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
      icon: '\u{1F3E5}',
      component: RepoHealthPanel,
      getCount: () => ossStage1.items.length
    },
    {
      id: 'assign',
      label: 'Fork & Assign',
      icon: '\u{1F531}',
      component: ForkAssignPanel,
      getCount: () => ossStage2.items.length
    },
    {
      id: 'pipeline',
      label: 'Pipeline Runs',
      icon: '\u{2699}\u{FE0F}',
      component: PipelineRunsPanel,
      getCount: () => ossPipelineRuns.items.length
    },
    {
      id: 'review',
      label: 'Review',
      icon: '\u{1F4CA}',
      component: ProductionReviewPanel,
      getCount: () => ossSubmittedPRs.items.length
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
      />
      <ProgressLog />
    </div>
  )
}
