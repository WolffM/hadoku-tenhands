/**
 * OSSView
 *
 * Main view for the 5-stage OSS contribution pipeline.
 * Stages 1-2 are stubs (aggregator integration in M2).
 * Stages 3-5 are fully functional.
 */

import { useEffect, useRef } from 'react'
import { usePipelineStore, selectIsOSSLoading } from '../store'
import { OSSTargetList } from '../components/oss/OSSTargetList'
import { OSSIssueList } from '../components/oss/OSSIssueList'
import { OSSAssignPanel } from '../components/oss/OSSAssignPanel'
import { OSSReviewPanel } from '../components/oss/OSSReviewPanel'
import { OSSSubmitPanel } from '../components/oss/OSSSubmitPanel'
import { ProgressLog, StageTabView, type StageTabConfig } from '../components/common'

export function OSSView() {
  const isLoading = usePipelineStore(selectIsOSSLoading)
  const loadAllOSSStages = usePipelineStore(state => state.loadAllOSSStages)

  const ossStage1 = usePipelineStore(state => state.ossStage1)
  const ossStage2 = usePipelineStore(state => state.ossStage2)
  const ossStage3 = usePipelineStore(state => state.ossStage3)
  const ossStage4 = usePipelineStore(state => state.ossStage4)
  const ossStage5 = usePipelineStore(state => state.ossStage5)

  // Load all OSS stages on mount
  const initialLoadDoneRef = useRef(false)
  useEffect(() => {
    if (initialLoadDoneRef.current) return
    initialLoadDoneRef.current = true
    void loadAllOSSStages()
  }, [loadAllOSSStages])

  const stages: StageTabConfig[] = [
    {
      id: 'target',
      label: 'Target Repos',
      icon: '\u{1F3AF}',
      component: OSSTargetList,
      getCount: () => ossStage1.items.length
    },
    {
      id: 'select',
      label: 'Select Issues',
      icon: '\u{1F4CB}',
      component: OSSIssueList,
      getCount: () => ossStage2.items.length
    },
    {
      id: 'assign',
      label: 'Fork & Assign',
      icon: '\u{1F531}',
      component: OSSAssignPanel,
      getCount: () => ossStage3.items.length
    },
    {
      id: 'review',
      label: 'Review on Fork',
      icon: '\u{1F441}',
      component: OSSReviewPanel,
      getCount: () => ossStage4.items.length
    },
    {
      id: 'submit',
      label: 'Submit Upstream',
      icon: '\u{1F4E4}',
      component: OSSSubmitPanel,
      getCount: () => ossStage5.items.length
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
        defaultStageId="assign"
      />
      <ProgressLog />
    </div>
  )
}
