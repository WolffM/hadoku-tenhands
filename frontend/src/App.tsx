import { useRef, useState, useEffect } from 'react'
import { ConnectedThemePicker, LoadingSkeleton } from '@wolffm/task-ui-components'
import { THEME_ICON_MAP } from '@wolffm/themes'
import { useTheme } from './hooks/useTheme'
import { usePipelineStore } from './store'
import { getOwner } from './api/endpoints'
import { Navigation } from './components/common'
import { VibecheckView, ReviewQueueView, HealthCheckView, OSSView } from './views'
import type { VibeDispatchProps } from './entry'

export default function App(props: VibeDispatchProps = {}) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Get active view and owner from store
  const activeView = usePipelineStore(state => state.activeView)
  const owner = usePipelineStore(state => state.owner)
  const setOwner = usePipelineStore(state => state.setOwner)

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
          console.error('Failed to fetch owner:', err)
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
      case 'review':
        return <ReviewQueueView />
      case 'health':
        return <HealthCheckView />
      case 'list':
      default:
        return <VibecheckView />
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
