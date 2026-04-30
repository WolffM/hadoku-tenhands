/**
 * Navigation Component
 *
 * Three always-visible top-level tabs: Home (pipeline picker), Retrospective,
 * Health. Individual pipelines (Vibecheck, OSS Contrib, Crimson-Kitty) are
 * NOT top-level tabs — pick one from Home, work inside it, click Home to
 * switch. Cleanup 2026-04-30 collapsed 7 tabs into 3 by removing redundant
 * pipeline-specific tabs and dropping the legacy Review Queue surface
 * (its data is reachable via Vibecheck Stage 4).
 */

import { usePipelineStore, type ViewType } from '../../store'

const TOP_TABS: { id: ViewType; label: string }[] = [
  { id: 'select', label: 'Home' },
  { id: 'retro', label: 'Retrospective' },
  { id: 'health', label: 'Health' }
]

export function Navigation() {
  const activeView = usePipelineStore(state => state.activeView)
  const setActiveView = usePipelineStore(state => state.setActiveView)

  return (
    <nav className="navigation">
      <div className="nav-tabs">
        {TOP_TABS.map(tab => (
          <button
            key={tab.id}
            className={`nav-tabs__tab ${activeView === tab.id ? 'nav-tabs__tab--active' : ''}`}
            onClick={() => setActiveView(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
    </nav>
  )
}
