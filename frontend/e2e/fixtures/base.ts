/**
 * Base fixture for the local suite.
 *
 * Three things happen automatically for every test:
 *   1. The API router is installed BEFORE the test body, so no request can
 *      reach the real backend — see `api.ts` for why that is the whole point.
 *   2. An endpoint the router had no entry for fails the test BY NAME.
 *   3. Console errors and page errors fail the test.
 *
 * (2) MUST out-speak (3), because a mock gap causes an aborted fetch which
 * causes a console error. If the console check spoke first, every gap would be
 * reported as "Test produced 1 console error" with a stack inside fetch — which
 * is exactly how the previous suite hid ~120 missing mocks behind what read as
 * product failures. Two independent things guarantee the right one wins:
 *
 *   - Declaration order. Fixtures tear down in REVERSE of setup, so
 *     `consoleErrors` is declared FIRST and `api` second, making `api` the
 *     first to tear down and throw. This is easy to get backwards; the test
 *     `harness.spec.ts` pins it.
 *   - The console filter drops "Failed to load resource"-class noise. With
 *     default-deny routing every API call is either fulfilled 200 or aborted
 *     and named by the router, so a load failure carries no information the
 *     router has not already reported more precisely.
 */

import { test as base, expect, type Page } from '@playwright/test'

import { installApi, type MockHandle, type Responder } from './api'

interface ConsoleEntry {
  type: string
  text: string
}

interface Fixtures {
  /** Per-test route overrides, merged over the defaults. Set with `test.use()`. */
  apiOverrides: Record<string, Responder>
  /** Recorded calls, POST bodies and unmocked misses for the current test. */
  api: MockHandle
  consoleErrors: ConsoleEntry[]
}

/** Console noise that is either irrelevant or already reported better elsewhere. */
function isNoise(text: string): boolean {
  return (
    text.includes('Download the React DevTools') ||
    text.includes('React Router Future Flag Warning') ||
    (text.includes('[vite]') && text.includes('hmr')) ||
    // Aborted request from the default-deny router. `api` names it precisely.
    text.includes('Failed to load resource') ||
    text.includes('net::ERR_FAILED') ||
    text.includes('Failed to fetch')
  )
}

export const test = base.extend<Fixtures>({
  apiOverrides: [{}, { option: true }],

  // Declared FIRST so it tears down LAST — see the header. Do not reorder.
  consoleErrors: [
    async ({ page }, use) => {
      const errors: ConsoleEntry[] = []

      page.on('console', msg => {
        const type = msg.type()
        if (type !== 'error' && type !== 'warning') return
        const text = msg.text()
        if (isNoise(text)) return
        errors.push({ type, text })
      })

      page.on('pageerror', err => {
        if (isNoise(err.message)) return
        errors.push({ type: 'pageerror', text: err.message })
      })

      await use(errors)

      if (errors.length > 0) {
        const summary = errors.map(e => `  [${e.type}] ${e.text}`).join('\n')
        throw new Error(`Test produced ${errors.length} console error(s)/warning(s):\n${summary}`)
      }
    },
    { auto: true }
  ],

  // Declared SECOND so it tears down FIRST and gets to speak before the
  // console check. See the header.
  api: [
    async ({ page, apiOverrides }, use) => {
      const handle = await installApi(page, apiOverrides)

      await use(handle)

      if (handle.unmocked.length > 0) {
        const unique = [...new Set(handle.unmocked)]
        throw new Error(
          `The UI called ${unique.length} endpoint(s) the mock router does not know:\n` +
            unique.map(u => `  ${u}`).join('\n') +
            `\n\nAdd them to defaultRoutes in e2e/fixtures/api.ts (or pass an override).\n` +
            `This is a gap in the harness, not a product failure.`
        )
      }
    },
    { auto: true }
  ]
})

export { expect }
export type { Page }
