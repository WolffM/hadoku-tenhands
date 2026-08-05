import { useRef, useState, useEffect, type RefObject } from 'react'
import { AppHeader, LoadingSkeleton } from '@wolffm/task-ui-components'
import { useHadokuTheme } from '@wolffm/themes'
import { HadokuThemeRoot } from '@wolffm/themes'
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
  TemporalPipelineView,
  TaskAutoView
} from './views'
import type { TenHandsProps } from './entry'

/**
 * Provider boundary. Theme state belongs to the platform (@wolffm/themes),
 * not to this app — the local hooks/useTheme.ts and app/themeConfig.tsx copies
 * are gone. AppHeader renders the shared picker from this context, so nothing
 * below passes one.
 */
export default function App(props: TenHandsProps = {}) {
  const containerRef = useRef<HTMLDivElement>(null)
  return (
    <HadokuThemeRoot theme={props.theme} containerRef={containerRef}>
      <AppInner {...props} containerRef={containerRef} />
    </HadokuThemeRoot>
  )
}

function AppInner(props: TenHandsProps & { containerRef: RefObject<HTMLDivElement | null> }) {
  const { containerRef } = props

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

  // Theme comes from <HadokuThemeRoot> above — one implementation for
  // every app, instead of this repo's former hooks/useTheme.ts copy.
  const { theme, isDarkTheme, isThemeReady, isInitialThemeLoad } = useHadokuTheme()

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
      case 'taskauto':
        return <TaskAutoView />
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
      className="tenhands-container"
      data-theme={theme}
      data-dark-theme={isDarkTheme ? 'true' : 'false'}
    >
      <div className="tenhands">
        <AppHeader
          title="TenHands"
        />

        <Navigation />

        <main className="tenhands__content">{renderView()}</main>
      </div>
    </div>
  )
}
