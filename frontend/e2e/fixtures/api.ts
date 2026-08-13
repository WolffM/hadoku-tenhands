/**
 * The local suite's API transport: one Playwright route handler, default-deny.
 *
 * WHY THIS SHAPE. The suite this replaces mocked endpoints opt-in, one
 * `page.route()` per endpoint per helper, and `mockAllAPIs()` wired up a subset
 * of them. Anything the UI called that no helper had claimed fell straight
 * through to the real Flask backend on :5001, which answers an unauthenticated
 * request with 401. The 401 logged a console error, and the console-error
 * fixture in `base.ts` failed the test — so a missing MOCK was reported as a
 * failing ASSERTION, in a spec that often had nothing to do with the endpoint.
 * Roughly 120 of 180 tests failed that way, all reading like product bugs.
 *
 * The fix is to make the mock layer total rather than additive:
 *
 *   1. ONE route covering every /tenhands/api path, so nothing reaches the
 *      network. A
 *      test cannot silently depend on a live backend any more.
 *   2. Every endpoint in `src/api/endpoints.ts` has a default response below.
 *      Views are free to fetch whatever they fetch.
 *   3. A request that matches no entry is NOT passed through and NOT quietly
 *      stubbed — it is recorded and fails the test by name, at teardown, with
 *      the method and path. A new endpoint shows up as "you forgot to mock
 *      GET /api/whatever", once, in the spec that triggered it.
 *
 * That last point is the whole design. The old suite's failure mode was that a
 * gap in the mocks was indistinguishable from a broken UI; here a gap says
 * exactly what it is.
 *
 * The route TABLE, the matcher, and the response types live in `./table`, with
 * no Playwright dependency, so the static demo build can reuse the same corpus
 * behind a `window.fetch` wrapper. This file is only the Playwright transport.
 */

import type { Page, Route } from '@playwright/test'

import { defaultRoutes, lookup, type Table } from './table'

// Re-export the corpus so existing spec imports (`from '../fixtures/api'`) keep
// working after the transport/data split. The demo build imports these straight
// from `./table` instead, to stay clear of this Playwright module.
export {
  defaultRoutes,
  lookup,
  ok,
  type Table,
  type Responder,
  type ResponderFn,
  type ResponseBody,
  type RequestContext
} from './table'

export interface MockHandle {
  /** Requests that matched no table entry. Asserted empty by the base fixture. */
  readonly unmocked: string[]
  /** Every request served, as `METHOD /path` — for asserting a call happened. */
  readonly calls: string[]
  /** Bodies of POSTs served, keyed by `METHOD /path`, newest last. */
  readonly posts: { key: string; body: Record<string, unknown> | undefined }[]
}

/**
 * Install the router on a page. `overrides` are merged over `defaultRoutes`,
 * which is how a spec says "this endpoint, for this test, returns that" without
 * re-declaring the other fifty.
 */
export async function installApi(page: Page, overrides: Table = {}): Promise<MockHandle> {
  const table: Table = { ...defaultRoutes, ...overrides }
  const unmocked: string[] = []
  const calls: string[] = []
  const posts: { key: string; body: Record<string, unknown> | undefined }[] = []

  await page.route('**/tenhands/api/**', async (route: Route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^.*?\/tenhands/, '')

    let body: Record<string, unknown> | undefined
    if (method === 'POST') {
      try {
        body = request.postDataJSON() as Record<string, unknown>
      } catch {
        body = undefined
      }
    }

    const responder = lookup(table, method, path)
    const key = `${method} ${path}`

    if (responder === undefined) {
      unmocked.push(key)
      // Abort rather than fulfil with an error status. A 4xx/5xx would make the
      // app log a console error, and the console-error fixture would then report
      // a mock gap as an assertion failure — exactly the confusion this replaces.
      // The teardown check below is the one that speaks.
      await route.abort('failed')
      return
    }

    calls.push(key)
    if (method === 'POST') posts.push({ key, body })

    const payload =
      typeof responder === 'function'
        ? responder({
            method,
            path,
            query: url.searchParams,
            body
          })
        : responder

    // Not everything under /api is JSON — the issue report is a standalone HTML
    // document. Serving it as application/json would make the client's
    // `res.json()` throw, which reads as a product bug rather than a fixture one.
    const isHtml = typeof payload === 'string' && payload.trimStart().startsWith('<')

    await route.fulfill({
      status: 200,
      contentType: isHtml ? 'text/html' : 'application/json',
      body: isHtml ? payload : JSON.stringify(payload)
    })
  })

  return { unmocked, calls, posts }
}
