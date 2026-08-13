/**
 * Entry point for the static, fixture-backed public demo.
 *
 * The order here is load-bearing: `installDemoFetch` MUST replace `window.fetch`
 * before the app mounts, or the app's first requests hit the network and 404.
 * Everything after that is the REAL app — the same `mount()` the published
 * library exposes — pointed at the in-page fixture corpus.
 */

// Theme tokens: provided globally by the parent (hadoku_site) in production, so
// entry.tsx does not import them. The standalone demo has no parent, so it must
// bundle them itself. The task-ui-components CSS is already imported by entry.
import '@wolffm/themes/style.css'

import { createRoot } from 'react-dom/client'

import { mount } from '../entry'
import { installDemoFetch } from './fetchStub'
import { overrides } from './overrides'
import { DemoBadge } from './DemoBadge'

installDemoFetch(overrides)

const appEl = document.getElementById('app')
if (appEl) {
  mount(appEl, { owner: 'WolffM' })
}

// The badge lives in its own root so it never interferes with the mounted app's
// React tree (unmount() on #app leaves it standing, which is what we want).
const badgeEl = document.createElement('div')
badgeEl.id = 'demo-badge-root'
document.body.appendChild(badgeEl)
createRoot(badgeEl).render(<DemoBadge />)
