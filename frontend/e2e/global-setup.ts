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

  // 2. gh CLI auth — non-fatal warning so tests that depend on it fail with clear names
  try {
    const res = await fetchWithTimeout(`${BACKEND_URL}/tenhands/api/oss/debug/gh-health`)
    if (res.ok) {
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
