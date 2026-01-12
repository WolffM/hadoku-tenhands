/**
 * Navigation Component
 *
 * Top navigation tabs for switching between views.
 */

import { usePipelineStore, selectReviewQueueCount, type ViewType } from '../../store'

export function Navigation() {
  const activeView = usePipelineStore(state => state.activeView)
  const setActiveView = usePipelineStore(state => state.setActiveView)
  const reviewCount = usePipelineStore(selectReviewQueueCount)

  const tabs: { id: ViewType; label: string; badge?: number }[] = [
    { id: 'list', label: 'Pipelines' },
    { id: 'review', label: 'Review Queue', badge: reviewCount },
    { id: 'health', label: 'Health' }
  ]

  return (
    <nav className="navigation">
      <div className="nav-tabs">
        {tabs.map(tab => (
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
