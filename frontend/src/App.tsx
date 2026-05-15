import { useRef, useState, useEffect } from 'react'
import { ConnectedThemePicker, LoadingSkeleton } from '@wolffm/task-ui-components'
import { THEME_ICON_MAP } from '@wolffm/themes'
import { useTheme } from './hooks/useTheme'
import { usePipelineStore, type ViewType } from './store'
import { useTemporalStore } from './store/temporalStore'
import { getOwner } from './api/endpoints'
import { Navigation } from './components/common'
import {
  VibecheckView,
  ReviewQueueView,
  HealthCheckView,
  OSSView,
  PipelineSelectView,
  RetroView,
  TemporalPipelineView
} from './views'
import type { VibeDispatchProps } from './entry'

export default function App(props: VibeDispatchProps = {}) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Get active view and owner from store
  const activeView = usePipelineStore(state => state.activeView)
  const setActiveView = usePipelineStore(state => state.setActiveView)
  const owner = usePipelineStore(state => state.owner)
  const setOwner = usePipelineStore(state => state.setOwner)
  const addLog = usePipelineStore(state => state.addLog)
  const loadTemporalBatch = useTemporalStore(state => state.loadBatch)
  const selectTemporalIssue = useTemporalStore(state => state.selectIssue)

  // Deep links from Discord notifications: ?view=temporal&batch=X&issue=Y
  // lands the operator on the temporal pipeline with the issue pre-selected.
  // Only consumed once on mount; subsequent in-app navigation is store-driven.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const view = params.get('view') as ViewType | null
    if (view && view !== 'select') {
      setActiveView(view)
    }
    const batch = params.get('batch')
    const issue = params.get('issue')
    if (view === 'temporal' && batch) {
      void loadTemporalBatch(batch).then(() => {
        if (issue) selectTemporalIssue(issue)
      })
    }
    // run once on mount
  }, [loadTemporalBatch, selectTemporalIssue, setActiveView])

  // Initialize owner from props or fetch from API
  useEffect(() => {
    const initOwner = async () => {
      // If owner prop provided, use it
      if (props.owner) {
        setOwner(props.owner)
        return
      }
      // Otherwise fetch from API
      if (!owner) {
        try {
          const response = await getOwner()
          if (response.success && response.owner) {
            setOwner(response.owner)
          }
        } catch (err) {
          addLog(
            `Failed to fetch owner: ${err instanceof Error ? err.message : String(err)}`,
            'error'
          )
        }
      }
    }
    void initOwner()
  }, [props.owner, owner, setOwner])

  // Detect system preference for loading skeleton
  const [systemPrefersDark] = useState(() => {
    if (window.matchMedia) {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
    }
    return false
  })

  const { theme, setTheme, isDarkTheme, isThemeReady, isInitialThemeLoad, THEME_FAMILIES } =
    useTheme({
      propsTheme: props.theme,
      experimentalThemes: false,
      containerRef
    })

  // Show loading skeleton during initial theme load to prevent FOUC
  if (isInitialThemeLoad && !isThemeReady) {
    return <LoadingSkeleton isDarkTheme={systemPrefersDark} />
  }

  // Render the active view
  const renderView = () => {
    switch (activeView) {
      case 'oss':
        return <OSSView />
      case 'temporal':
        return <TemporalPipelineView />
      case 'retro':
        return <RetroView />
      case 'review':
        return <ReviewQueueView />
      case 'health':
        return <HealthCheckView />
      case 'list':
        return <VibecheckView />
      case 'select':
      default:
        return <PipelineSelectView />
    }
  }

  return (
    <div
      ref={containerRef}
      className="vibedispatch-container"
      data-theme={theme}
      data-dark-theme={isDarkTheme ? 'true' : 'false'}
    >
      <div className="vibedispatch">
        <header className="vibedispatch__header">
          <h1 className="vibedispatch__title">VibeDispatch</h1>
          <Navigation />
          <div className="vibedispatch__actions">
            <ConnectedThemePicker
              themeFamilies={THEME_FAMILIES}
              currentTheme={theme}
              onThemeChange={setTheme}
              getThemeIcon={(themeName: string) => {
                const Icon = THEME_ICON_MAP[themeName as keyof typeof THEME_ICON_MAP]
                return Icon ? <Icon /> : null
              }}
            />
          </div>
        </header>

        <main className="vibedispatch__content">{renderView()}</main>
      </div>
    </div>
  )
}
