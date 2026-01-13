/**
 * VibecheckView
 *
 * Main view for the 4-stage vibecheck pipeline.
 * Mirrors the original global_actions.html structure.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
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
  const isLoading = usePipelineStore(selectIsLoading)
  const loadedStagesRef = useRef<Set<StageTab>>(new Set())

  // Individual stage loaders
  const loadStage1 = usePipelineStore(state => state.loadStage1)
  const loadStage2 = usePipelineStore(state => state.loadStage2)
  const loadStage3 = usePipelineStore(state => state.loadStage3)
  const loadStage4 = usePipelineStore(state => state.loadStage4)
  const loadAllStages = usePipelineStore(state => state.loadAllStages)

  // Stage counts
  const stage1 = usePipelineStore(state => state.stage1)
  const stage2 = usePipelineStore(state => state.stage2)
  const stage3 = usePipelineStore(state => state.stage3)
  const stage4 = usePipelineStore(state => state.stage4)

  // Load stage function based on stage ID
  const loadStage = useCallback(
    (stageId: StageTab) => {
      if (loadedStagesRef.current.has(stageId)) return
      loadedStagesRef.current.add(stageId)

      switch (stageId) {
        case 'stage1':
          void loadStage1()
          break
        case 'stage2':
          void loadStage2()
          break
        case 'stage3':
          void loadStage3()
          break
        case 'stage4':
          void loadStage4()
          break
      }
    },
    [loadStage1, loadStage2, loadStage3, loadStage4]
  )

  // Track if initial load has happened
  const initialLoadDoneRef = useRef(false)

  // Load all stages on mount (active stage loads first due to lazy loading in each component)
  useEffect(() => {
    if (initialLoadDoneRef.current) return
    initialLoadDoneRef.current = true

    // Load all stages - they're tracked by loadedStagesRef to prevent duplicates
    STAGES.forEach(stage => loadStage(stage.id))
  }, [loadStage])

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
