/**
 * VibecheckView
 *
 * Main view for the 4-stage vibecheck pipeline.
 * Mirrors the original global_actions.html structure.
 */

import { useState, useEffect } from 'react'
import { usePipelineStore, selectIsLoading } from '../store'
import { Stage1Install } from '../components/vibecheck/Stage1Install'
import { Stage2Run } from '../components/vibecheck/Stage2Run'
import { Stage3Assign } from '../components/vibecheck/Stage3Assign'
import { Stage4Review } from '../components/vibecheck/Stage4Review'
import { ProgressLog } from '../components/common'

type StageTab = 'stage1' | 'stage2' | 'stage3' | 'stage4'

interface StageConfig {
  id: StageTab
  label: string
  icon: string
}

const STAGES: StageConfig[] = [
  { id: 'stage1', label: 'Install VibeCheck', icon: '📥' },
  { id: 'stage2', label: 'Run VibeCheck', icon: '▶️' },
  { id: 'stage3', label: 'Assign Copilot', icon: '🤖' },
  { id: 'stage4', label: 'Review & Merge', icon: '🔀' }
]

export function VibecheckView() {
  const [activeStage, setActiveStage] = useState<StageTab>('stage1')
  const loadAllStages = usePipelineStore(state => state.loadAllStages)
  const isLoading = usePipelineStore(selectIsLoading)

  // Stage counts
  const stage1 = usePipelineStore(state => state.stage1)
  const stage2 = usePipelineStore(state => state.stage2)
  const stage3 = usePipelineStore(state => state.stage3)
  const stage4 = usePipelineStore(state => state.stage4)

  // Load all stages on mount
  useEffect(() => {
    void loadAllStages()
  }, [loadAllStages])

  const getStageCounts = (): Record<StageTab, number> => ({
    stage1: stage1.items.length,
    stage2: stage2.items.length,
    stage3: stage3.items.length,
    stage4: stage4.items.filter(pr => isPRReady(pr)).length
  })

  const stageCounts = getStageCounts()

  const renderStageContent = () => {
    switch (activeStage) {
      case 'stage1':
        return <Stage1Install />
      case 'stage2':
        return <Stage2Run />
      case 'stage3':
        return <Stage3Assign />
      case 'stage4':
        return <Stage4Review />
      default:
        return null
    }
  }

  return (
    <div className="vibecheck-view">
      {/* Stage Tabs */}
      <div className="stage-tabs">
        {STAGES.map(stage => (
          <button
            key={stage.id}
            className={`stage-tab ${activeStage === stage.id ? 'stage-tab--active' : ''}`}
            onClick={() => setActiveStage(stage.id)}
          >
            <span className="stage-tab__icon">{stage.icon}</span>
            <span className="stage-tab__label">{stage.label}</span>
            <span className="stage-tab__count">{stageCounts[stage.id]}</span>
          </button>
        ))}
        <div className="stage-tabs__actions">
          <button
            className="btn btn--primary btn--sm"
            onClick={() => {
              void loadAllStages()
            }}
            disabled={isLoading}
          >
            {isLoading ? 'Refreshing...' : 'Refresh All'}
          </button>
        </div>
      </div>

      {/* Stage Content */}
      <div className="stage-content">{renderStageContent()}</div>

      {/* Progress Log */}
      <ProgressLog />
    </div>
  )
}

// Helper to check if PR is ready for review
function isPRReady(pr: {
  isDraft?: boolean
  copilotCompleted?: boolean | null
  author?: { login: string } | null
}): boolean {
  const author = pr.author?.login ?? ''
  const isCopilot = author.toLowerCase().includes('copilot')

  if (isCopilot) {
    return pr.copilotCompleted === true
  }
  return !pr.isDraft
}
