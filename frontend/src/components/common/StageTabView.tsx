/**
 * StageTabView
 *
 * Generic tabbed stage view that renders a config-driven set of tabs
 * with count badges and a refresh button. Used by workflow views
 * to avoid duplicating tab switching logic.
 */

import { useState, type ComponentType } from 'react'

export interface StageTabConfig {
  id: string
  label: string
  icon: string
  component: ComponentType
  getCount: () => number
}

interface StageTabViewProps {
  stages: StageTabConfig[]
  isLoading: boolean
  onRefreshAll: () => void
  defaultStageId?: string
}

export function StageTabView({
  stages,
  isLoading,
  onRefreshAll,
  defaultStageId
}: StageTabViewProps) {
  const [activeStageId, setActiveStageId] = useState(defaultStageId ?? stages[0]?.id ?? '')

  const activeStage = stages.find(s => s.id === activeStageId)
  const ActiveComponent = activeStage?.component ?? null

  return (
    <>
      {/* Stage Tabs */}
      <div className="stage-tabs">
        {stages.map(stage => (
          <button
            key={stage.id}
            className={`stage-tab ${activeStageId === stage.id ? 'stage-tab--active' : ''}`}
            onClick={() => setActiveStageId(stage.id)}
          >
            <span className="stage-tab__icon">{stage.icon}</span>
            <span className="stage-tab__label">{stage.label}</span>
            <span className="stage-tab__count">{stage.getCount()}</span>
          </button>
        ))}
        <div className="stage-tabs__actions">
          <button className="btn btn--primary btn--sm" onClick={onRefreshAll} disabled={isLoading}>
            {isLoading ? 'Refreshing...' : 'Refresh All'}
          </button>
        </div>
      </div>

      {/* Stage Content */}
      <div className="stage-content">{ActiveComponent && <ActiveComponent />}</div>
    </>
  )
}
