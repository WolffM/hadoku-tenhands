/**
 * Production E2E test fixture with full audit trail.
 *
 * Captures ALL console logs (not just errors) and ALL network requests
 * to /tenhands/api/** as test attachments for post-mortem analysis.
 *
 * Usage: import { test, expect } from '../fixtures/prod-base'
 */

import { test as base, expect, type Page, type TestInfo } from '@playwright/test'

// ---------- Types ----------

interface ConsoleEntry {
  timestamp: string
  type: string // 'log' | 'info' | 'debug' | 'warning' | 'error' | 'pageerror'
  text: string
}

interface NetworkEntry {
  timestamp: string
  method: string
  url: string
  status: number | null
  duration_ms: number | null
  requestBody: string | null
  responseBody: string | null
  isOSSAPI: boolean
  isError: boolean // non-2xx
}

export interface AuditTrail {
  console: ConsoleEntry[]
  network: NetworkEntry[]
  errors: ConsoleEntry[] // subset: just errors/warnings
  failedRequests: NetworkEntry[] // subset: non-2xx API calls
  apiFailures: NetworkEntry[] // subset: 2xx but {"success":false} in body
}

// ---------- Fixture ----------

export const test = base.extend<{
  auditTrail: AuditTrail
}>({
  auditTrail: [
    async ({ page }, use, testInfo) => {
      const trail: AuditTrail = {
        console: [],
        network: [],
        errors: [],
        failedRequests: [],
        apiFailures: []
      }

      // --- Console capture (ALL levels) ---
      page.on('console', msg => {
        const type = msg.type()
        const text = msg.text()
        const entry: ConsoleEntry = {
          timestamp: new Date().toISOString(),
          type,
          text
        }
        trail.console.push(entry)

        // Track errors/warnings for fail-on-error (same filter as base.ts)
        if (type === 'error' || type === 'warning') {
          if (text.includes('Download the React DevTools')) return
          if (text.includes('React Router Future Flag Warning')) return
          if (text.includes('[vite]') && text.includes('hmr')) return
          trail.errors.push(entry)
        }
      })

      page.on('pageerror', err => {
        const entry: ConsoleEntry = {
          timestamp: new Date().toISOString(),
          type: 'pageerror',
          text: err.message
        }
        trail.console.push(entry)
        trail.errors.push(entry)
      })

      // --- Network capture ---
      const requestTimings = new Map<string, number>()

      page.on('request', request => {
        requestTimings.set(request.url() + request.method(), Date.now())
      })

      page.on('response', async response => {
        const request = response.request()
        const url = request.url()
        const method = request.method()
        const isAPI = url.includes('/tenhands/api/')
        const isOSSAPI = url.includes('/tenhands/api/oss/')

        // Only log API calls, not static assets
        if (!isAPI) return

        const startTime = requestTimings.get(url + method)
        const duration = startTime ? Date.now() - startTime : null
        const status = response.status()
        const isError = status >= 400

        let requestBody: string | null = null
        let responseBody: string | null = null

        // Capture bodies for OSS API calls (avoid noise from static assets)
        if (isOSSAPI) {
          try {
            requestBody = request.postData() ?? null
          } catch {
            /* no body */
          }
          try {
            responseBody = await response.text()
          } catch {
            /* stream consumed */
          }
        }

        const entry: NetworkEntry = {
          timestamp: new Date().toISOString(),
          method,
          url,
          status,
          duration_ms: duration,
          requestBody,
          responseBody,
          isOSSAPI,
          isError
        }
        trail.network.push(entry)

        if (isError && isOSSAPI) {
          trail.failedRequests.push(entry)
        }

        // Detect server-reported failures: HTTP 200 but {"success":false}
        if (!isError && isOSSAPI && responseBody) {
          try {
            const parsed = JSON.parse(responseBody) as Record<string, unknown>
            if (parsed && parsed.success === false) {
              trail.apiFailures.push(entry)
            }
          } catch {
            /* not JSON, skip */
          }
        }
      })

      // --- Run the test ---
      await use(trail)

      // --- Post-test: attach audit trail ---
      if (trail.console.length > 0) {
        await testInfo.attach('console-log', {
          body: JSON.stringify(trail.console, null, 2),
          contentType: 'application/json'
        })
      }

      const apiRequests = trail.network.filter(n => n.isOSSAPI)
      if (apiRequests.length > 0) {
        await testInfo.attach('oss-api-trace', {
          body: JSON.stringify(apiRequests, null, 2),
          contentType: 'application/json'
        })
      }

      if (trail.failedRequests.length > 0) {
        await testInfo.attach('failed-requests', {
          body: JSON.stringify(trail.failedRequests, null, 2),
          contentType: 'application/json'
        })
      }

      if (trail.apiFailures.length > 0) {
        await testInfo.attach('api-failures', {
          body: JSON.stringify(trail.apiFailures, null, 2),
          contentType: 'application/json'
        })
      }

      // Fail on HTTP errors (non-2xx OSS API responses)
      if (trail.failedRequests.length > 0) {
        const summary = trail.failedRequests
          .map(r => `  [${r.status}] ${r.method} ${r.url}`)
          .join('\n')
        throw new Error(
          `Test produced ${trail.failedRequests.length} failed HTTP request(s):\n${summary}`
        )
      }

      // Fail on server-reported errors (200 but {"success":false})
      if (trail.apiFailures.length > 0) {
        const summary = trail.apiFailures
          .map(r => {
            let err = ''
            try {
              const parsed = JSON.parse(r.responseBody ?? '{}') as Record<string, unknown>
              err = typeof parsed.error === 'string' ? parsed.error : ''
            } catch {
              /* */
            }
            return `  [${r.method} ${r.url}] ${err}`
          })
          .join('\n')
        throw new Error(
          `Test produced ${trail.apiFailures.length} API failure(s) (success:false):\n${summary}`
        )
      }

      // Fail on browser console errors/warnings
      if (trail.errors.length > 0) {
        const summary = trail.errors.map(e => `  [${e.type}] ${e.text}`).join('\n')
        throw new Error(
          `Test produced ${trail.errors.length} console error(s)/warning(s):\n${summary}`
        )
      }
    },
    { auto: true }
  ]
})

export { expect }
export type { Page, TestInfo, ConsoleEntry, NetworkEntry }
