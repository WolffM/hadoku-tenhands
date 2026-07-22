import { createRoot, type Root } from 'react-dom/client'
import { logger } from '@wolffm/logger/client'
import App from './App'
// @wolffm/themes/style.css tokens are provided globally by the parent
// (hadoku_site global.css). The task-ui-components component CSS is NOT global,
// so bundle it here — otherwise the unified header + theme picker render
// unstyled wherever this app is mounted. (These previously lived in index.html,
// which only applies to the dev server, never the published library bundle.)
import '@wolffm/task-ui-components/theme-picker.css'
import '@wolffm/task-ui-components/app-header.css'
import './styles/index.css'

// Props interface for configuration from parent app
export interface TenHandsProps {
  theme?: string // Theme passed from parent (e.g., 'default', 'ocean', 'forest')
  owner?: string // GitHub owner/user (if not provided, fetched from API)
}

// Extend HTMLElement to include __root property
interface TenHandsElement extends HTMLElement {
  __root?: Root
}

// Mount function - called by parent to initialize your app
export function mount(el: HTMLElement, props: TenHandsProps = {}) {
  const root = createRoot(el)
  root.render(<App {...props} />)
  ;(el as TenHandsElement).__root = root
  logger.info('[tenhands] Mounted successfully', { theme: props.theme })
}

// Unmount function - called by parent to cleanup your app
export function unmount(el: HTMLElement) {
  ;(el as TenHandsElement).__root?.unmount()
  logger.info('[tenhands] Unmounted successfully')
}
