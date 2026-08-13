/**
 * In-page fetch stub for the static demo build.
 *
 * The demo mounts the REAL app with zero backend. Instead of Playwright's
 * `page.route()`, this wraps `window.fetch`: any request to `/tenhands/api/*`
 * is answered from the SAME fixture corpus the e2e suite uses
 * (`e2e/fixtures/table.ts`), so the demo can never drift from the tests.
 * Everything else — JS chunks, CSS, fonts — falls through to the browser's
 * real fetch untouched.
 *
 * Content-type and prefix handling mirror `e2e/fixtures/api.ts` exactly, so a
 * responder that produces an HTML string (the OSS issue report) is served as
 * `text/html` and JSON otherwise.
 */

import { defaultRoutes, lookup, type Table, type ResponseBody } from '../../e2e/fixtures/table'

/** How api.ts derives the prefixless path: drop everything up to and incl. `/tenhands`. */
const PREFIX_RE = /^.*?\/tenhands/

/** Artificial latency so the app's loading states are actually visible. */
function demoDelay(): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, 150 + Math.floor(Math.random() * 250)))
}

/** Pull a usable URL + method + JSON body out of whatever fetch was called with. */
function describe(
  input: RequestInfo | URL,
  init?: RequestInit
): { url: URL; method: string; rawBody: string | undefined } {
  let href: string
  let method = init?.method ?? 'GET'
  let rawBody: string | undefined

  if (typeof input === 'string') {
    href = input
  } else if (input instanceof URL) {
    href = input.href
  } else {
    // Request object
    href = input.url
    method = init?.method ?? input.method ?? 'GET'
  }

  if (typeof init?.body === 'string') {
    rawBody = init.body
  }

  return {
    url: new URL(href, window.location.origin),
    method: method.toUpperCase(),
    rawBody
  }
}

function jsonResponse(payload: ResponseBody, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' }
  })
}

/**
 * Install the demo fetch wrapper. Call BEFORE the app mounts. `overrides` are
 * merged over `defaultRoutes` — the curated showcase deltas live in
 * `./overrides.ts`.
 */
export function installDemoFetch(overrides: Table = {}): void {
  const table: Table = { ...defaultRoutes, ...overrides }
  const originalFetch = window.fetch.bind(window)

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const { url, method, rawBody } = describe(input, init)

    // Non-API URLs (assets, chunks) go straight to the real fetch.
    if (!url.pathname.includes('/tenhands/api/')) {
      return originalFetch(input, init)
    }

    const path = url.pathname.replace(PREFIX_RE, '')

    let body: Record<string, unknown> | undefined
    if (method === 'POST' && rawBody) {
      try {
        body = JSON.parse(rawBody) as Record<string, unknown>
      } catch {
        body = undefined
      }
    }

    await demoDelay()

    const responder = lookup(table, method, path)

    if (responder === undefined) {
      // The demo analog of the suite's default-deny: nothing matched, so say so
      // loudly and hand back a 404 rather than silently pretending success.
      console.warn(`[demo] unmocked request: ${method} ${path}`)
      return jsonResponse({ success: false, error: `No demo fixture for ${method} ${path}` }, 404)
    }

    const payload =
      typeof responder === 'function'
        ? responder({ method, path, query: url.searchParams, body })
        : responder

    // Mirror api.ts: an HTML string body (the standalone issue report) is served
    // as text/html; everything else is JSON.
    const isHtml = typeof payload === 'string' && payload.trimStart().startsWith('<')
    if (isHtml) {
      return new Response(payload, { status: 200, headers: { 'Content-Type': 'text/html' } })
    }
    return jsonResponse(payload)
  }
}
