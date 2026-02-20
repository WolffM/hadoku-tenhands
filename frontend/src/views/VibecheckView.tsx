/**
 * VibecheckView
 *
 * Main view for the 4-stage vibecheck pipeline.
 * Mirrors the original global_actions.html structure.
 */

import { useEffect, useRef } from 'react'
import { usePipelineStore, selectIsLoading } from '../store'
import { Stage1Install } from '../components/vibecheck/Stage1Install'
import { Stage2Run } from '../components/vibecheck/Stage2Run'
import { Stage3Assign } from '../components/vibecheck/Stage3Assign'
import { Stage4Review } from '../components/vibecheck/Stage4Review'
import { ProgressLog, StageTabView, type StageTabConfig } from '../components/common'
import { isPRReady } from '../utils'

export function VibecheckView() {
  const isLoading = usePipelineStore(selectIsLoading)
  const loadAllStages = usePipelineStore(state => state.loadAllStages)

  const stage1 = usePipelineStore(state => state.stage1)
  const stage2 = usePipelineStore(state => state.stage2)
  const stage3 = usePipelineStore(state => state.stage3)
  const stage4 = usePipelineStore(state => state.stage4)

  // Load all stages on mount
  const initialLoadDoneRef = useRef(false)
  useEffect(() => {
    if (initialLoadDoneRef.current) return
    initialLoadDoneRef.current = true
    void loadAllStages()
  }, [loadAllStages])

  const stages: StageTabConfig[] = [
    {
      id: 'stage1',
      label: 'Install VibeCheck',
      icon: '\u{1F4E5}',
      component: Stage1Install,
      getCount: () => stage1.items.length
    },
    {
      id: 'stage2',
      label: 'Run VibeCheck',
      icon: '\u25B6\uFE0F',
      component: Stage2Run,
      getCount: () => stage2.items.length
    },
    {
      id: 'stage3',
      label: 'Assign Copilot',
      icon: '\u{1F916}',
      component: Stage3Assign,
      getCount: () => stage3.items.length
    },
    {
      id: 'stage4',
      label: 'Review & Merge',
      icon: '\u{1F500}',
      component: Stage4Review,
      getCount: () => stage4.items.filter(pr => isPRReady(pr)).length
    }
  ]

  return (
    <div className="vibecheck-view">
      <StageTabView
        stages={stages}
        isLoading={isLoading}
        onRefreshAll={() => {
          void loadAllStages()
        }}
      />
      <ProgressLog />
    </div>
  )
}
