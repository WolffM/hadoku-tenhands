import { createRoot, type Root } from 'react-dom/client'
import { logger } from '@wolffm/task-ui-components'
import App from './App'
// Parent app must provide @wolffm/themes/style.css (loaded via global.css in hadoku_site)
// Parent app must provide @wolffm/task-ui-components/theme-picker.css
import './styles/index.css'

// Props interface for configuration from parent app
export interface VibeDispatchProps {
  theme?: string // Theme passed from parent (e.g., 'default', 'ocean', 'forest')
  owner?: string // GitHub owner/user (if not provided, fetched from API)
}

// Extend HTMLElement to include __root property
interface VibeDispatchElement extends HTMLElement {
  __root?: Root
}

// Mount function - called by parent to initialize your app
export function mount(el: HTMLElement, props: VibeDispatchProps = {}) {
  const root = createRoot(el)
  root.render(<App {...props} />)
  ;(el as VibeDispatchElement).__root = root
  logger.info('[vibedispatch] Mounted successfully', { theme: props.theme })
}

// Unmount function - called by parent to cleanup your app
export function unmount(el: HTMLElement) {
  ;(el as VibeDispatchElement).__root?.unmount()
  logger.info('[vibedispatch] Unmounted successfully')
}
