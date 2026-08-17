/**
 * StageTabView
 *
 * The one tab strip every pipeline view renders. Two ways to drive it:
 *
 *   - Uncontrolled: pass `component` per stage and the view swaps content
 *     itself (Vibecheck, OSS).
 *   - Controlled: pass `activeId` + `onChange` and render the body yourself
 *     (Temporal needs this for deep-link tab sync; TaskAuto and Retro render
 *     their bodies below the strip).
 *
 * Icons, counts, the refresh button, and per-tab testids are all optional so
 * a two-tab strip with none of them renders as just two buttons.
 */

import { useState, type ComponentType, type ReactNode } from 'react'
import { Icon, type IconName } from '@wolffm/themes'

export interface StageTabConfig {
  id: string
  label: string
  /**
   * A registry name, NOT a glyph. Typed so a name outside the registry fails the
   * build: as a plain `string` this rendered its own value, and the icon
   * migration shipped tab strips reading "download" and "robot" as literal text.
   */
  icon?: IconName
  component?: ComponentType
  getCount?: () => number
  /** Per-tab data-testid, e.g. `temporal-tab-inbox`. */
  testId?: string
}

interface StageTabViewProps {
  stages: StageTabConfig[]
  isLoading?: boolean
  /** Renders the refresh button in the strip only when provided. */
  onRefreshAll?: () => void
  refreshLabel?: string
  defaultStageId?: string
  extraActions?: ReactNode
  /** Controlled mode: the active tab id. Pair with `onChange`. */
  activeId?: string
  onChange?: (id: string) => void
  /** data-testid for the strip element itself. */
  testId?: string
}

export function StageTabView({
  stages,
  isLoading = false,
  onRefreshAll,
  refreshLabel = 'Refresh All',
  defaultStageId,
  extraActions,
  activeId,
  onChange,
  testId
}: StageTabViewProps) {
  const [internalId, setInternalId] = useState(defaultStageId ?? stages[0]?.id ?? '')
  const activeStageId = activeId ?? internalId

  const selectStage = (id: string) => {
    if (activeId === undefined) setInternalId(id)
    onChange?.(id)
  }

  const activeStage = stages.find(s => s.id === activeStageId)
  const ActiveComponent = activeStage?.component ?? null

  return (
    <>
      <nav className="stage-tabs" data-testid={testId}>
        {stages.map(stage => (
          <button
            key={stage.id}
            type="button"
            className={`stage-tab ${activeStageId === stage.id ? 'stage-tab--active' : ''}`}
            data-testid={stage.testId}
            onClick={() => selectStage(stage.id)}
          >
            {stage.icon && (
              <span className="stage-tab__icon">
                <Icon name={stage.icon} />
              </span>
            )}
            <span className="stage-tab__label">{stage.label}</span>
            {stage.getCount && <span className="stage-tab__count">{stage.getCount()}</span>}
          </button>
        ))}
        {(extraActions || onRefreshAll) && (
          <div className="stage-tabs__actions">
            {extraActions}
            {onRefreshAll && (
              <button
                type="button"
                className="btn btn--primary btn--sm"
                onClick={onRefreshAll}
                disabled={isLoading}
              >
                {isLoading ? 'Refreshing…' : refreshLabel}
              </button>
            )}
          </div>
        )}
      </nav>

      {ActiveComponent && (
        <div className="stage-content">
          <ActiveComponent />
        </div>
      )}
    </>
  )
}
