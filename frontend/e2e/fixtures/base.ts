/**
 * Base test fixture that automatically fails tests on console errors/warnings.
 *
 * Usage: import { test, expect } from './fixtures/base' instead of '@playwright/test'
 */

import { test as base, expect, type Page } from '@playwright/test'

interface ConsoleEntry {
  type: string
  text: string
}

export const test = base.extend<{ consoleErrors: ConsoleEntry[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: ConsoleEntry[] = []

      page.on('console', msg => {
        const type = msg.type()
        if (type === 'error' || type === 'warning') {
          const text = msg.text()
          // Ignore known noise
          if (text.includes('Download the React DevTools')) return
          if (text.includes('React Router Future Flag Warning')) return
          if (text.includes('[vite]') && text.includes('hmr')) return
          errors.push({ type, text })
        }
      })

      page.on('pageerror', err => {
        errors.push({ type: 'pageerror', text: err.message })
      })

      await use(errors)

      // After test: fail if there were console errors
      if (errors.length > 0) {
        const summary = errors.map(e => `  [${e.type}] ${e.text}`).join('\n')
        throw new Error(`Test produced ${errors.length} console error(s)/warning(s):\n${summary}`)
      }
    },
    { auto: true }
  ]
})

export { expect }
export type { Page }
