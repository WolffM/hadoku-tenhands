/**
 * Global setup — runs once before any test, after webServer is started.
 *
 * Playwright's webServer already ensures both servers are accepting connections
 * before this runs. This adds two checks webServer can't do:
 *   1. Backend response content — verifies {"success":true}, not just HTTP 200
 *   2. gh CLI auth — warns if gh isn't authenticated so failures are obvious
 *
 * Fails fast with a clear error rather than 57 cryptic test failures.
 */

const BACKEND_URL = `http://localhost:${process.env.PW_BACKEND_PORT ?? '5001'}`
const TIMEOUT_MS = 10_000

async function fetchWithTimeout(url: string): Promise<Response> {
  const controller = new AbortController()
  const id = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    return await fetch(url, { signal: controller.signal })
  } finally {
    clearTimeout(id)
  }
}

export default async function globalSetup(): Promise<void> {
  const errors: string[] = []

  // 1. Backend response content (webServer only checks HTTP status, not body)
  try {
    const res = await fetchWithTimeout(`${BACKEND_URL}/tenhands/api/healthcheck`)
    if (!res.ok) {
      errors.push(`Backend returned HTTP ${res.status} — expected 200`)
    } else {
      const body = (await res.json()) as { success?: boolean; status?: string }
      if (!body.success) {
        errors.push(`Backend healthcheck success=false: ${JSON.stringify(body)}`)
      }
    }
  } catch (e) {
    errors.push(
      `Backend unreachable at ${BACKEND_URL}: ${e instanceof Error ? e.message : String(e)}\n  → cd backend && python3 app.py`
    )
  }

  if (errors.length > 0) {
    throw new Error(
      `\n\nPre-run environment check failed:\n${errors.map(e => `  ✘ ${e}`).join('\n')}\n\nFix the above before running e2e tests.\n`
    )
  }

  // 2. gh CLI auth — non-fatal, and deliberately quiet about the one answer it
  //    cannot interpret.
  //
  //    This probe is unauthenticated, and `/oss/debug/gh-health` is behind the
  //    backend's auth gate, so on a normal local run it gets a 401. The old code
  //    only acted `if (res.ok)`, so a 401 meant it silently did nothing — while
  //    still printing `"GET .../gh-health HTTP/1.1" 401` into the Flask log that
  //    scrolls past during every run. That line reads like a test failing on a
  //    permission problem and is the first thing you chase when the suite is
  //    red. It is not: it is this check, and it has no bearing on any test.
  //
  //    The local specs do not touch gh at all now — every request is served by
  //    the mock router in `fixtures/api.ts` — so this is only useful for the
  //    `prod` project. Say what a 401 actually means instead of leaving the log
  //    line to be misread.
  try {
    const res = await fetchWithTimeout(`${BACKEND_URL}/tenhands/api/oss/debug/gh-health`)
    if (res.status === 401) {
      console.info(
        `ℹ  gh-health probe got 401 (auth gate) — expected without a key, and irrelevant to the local suite.`
      )
    } else if (res.ok) {
      const body = (await res.json()) as { authenticated?: boolean; api_working?: boolean }
      if (!body.authenticated || !body.api_working) {
        console.warn(
          `\n⚠  gh CLI not authenticated — gh-dependent tests will fail\n   Run: gh auth login\n`
        )
      }
    }
  } catch {
    /* non-fatal */
  }
}
