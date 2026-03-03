/**
 * Navigation Component
 *
 * Top navigation tabs for switching between views.
 * Shows Home + pipeline tabs when not on the select view, and global tabs (Review Queue, Health) always.
 */

import { usePipelineStore, selectReviewQueueCount, type ViewType } from '../../store'

export function Navigation() {
  const activeView = usePipelineStore(state => state.activeView)
  const setActiveView = usePipelineStore(state => state.setActiveView)
  const reviewCount = usePipelineStore(selectReviewQueueCount)

  const showPipelineTabs = activeView !== 'select'

  const globalTabs: { id: ViewType; label: string; badge?: number }[] = [
    { id: 'review', label: 'Review Queue', badge: reviewCount },
    { id: 'health', label: 'Health' }
  ]

  const pipelineTabs: { id: ViewType; label: string }[] = [
    { id: 'list', label: 'Pipelines' },
    { id: 'oss', label: 'OSS Contrib' }
  ]

  return (
    <nav className="navigation">
      <div className="nav-tabs">
        {showPipelineTabs && (
          <button
            className="nav-tabs__tab nav-tabs__tab--home"
            onClick={() => setActiveView('select')}
          >
            Home
          </button>
        )}
        {showPipelineTabs &&
          pipelineTabs.map(tab => (
            <button
              key={tab.id}
              className={`nav-tabs__tab ${activeView === tab.id ? 'nav-tabs__tab--active' : ''}`}
              onClick={() => setActiveView(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        {globalTabs.map(tab => (
          <button
            key={tab.id}
            className={`nav-tabs__tab ${activeView === tab.id ? 'nav-tabs__tab--active' : ''}`}
            onClick={() => setActiveView(tab.id)}
          >
            {tab.label}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span className="nav-tabs__badge">{tab.badge}</span>
            )}
          </button>
        ))}
      </div>
    </nav>
  )
}
