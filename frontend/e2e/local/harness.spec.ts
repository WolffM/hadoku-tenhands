/**
 * Tests for the test harness itself.
 *
 * The suite this replaced was ~120/180 red, and every one of those failures was
 * reported as a product problem when it was actually a missing mock. The
 * properties that prevent a repeat are load-bearing, so they are pinned here
 * rather than left as comments in `api.ts`.
 *
 * These use the RAW Playwright `test`, not the extended one from `base.ts`.
 * That is deliberate: the behaviour under test is an auto-fixture that throws
 * at teardown, and a spec using it could not observe that without failing.
 */

import { test, expect } from '@playwright/test'

import { installApi, defaultRoutes } from '../fixtures/api'

const API = 'http://localhost:5184/tenhands/api'

test.describe('mock router', () => {
  test('serves a default response without touching the network', async ({ page }) => {
    const api = await installApi(page)
    await page.goto('/')

    const body = await page.evaluate(async (url: string) => {
      const res = await fetch(`${url}/owner`)
      return (await res.json()) as { success: boolean; owner: string }
    }, API)

    expect(body.success).toBe(true)
    expect(body.owner).toBe('test-user')
    expect(api.unmocked).toEqual([])
    expect(api.calls).toContain('GET /api/owner')
  })

  test('records an endpoint it has no entry for instead of passing it through', async ({
    page
  }) => {
    // The critical property. Previously this request reached Flask on :5001,
    // came back 401, and surfaced as a console-error assertion failure in
    // whatever spec happened to trigger it.
    const api = await installApi(page)
    await page.goto('/')

    await page.evaluate(async (url: string) => {
      await fetch(`${url}/definitely-not-a-real-endpoint`).catch(() => undefined)
    }, API)

    expect(api.unmocked).toContain('GET /api/definitely-not-a-real-endpoint')
    expect(api.calls).not.toContain('GET /api/definitely-not-a-real-endpoint')
  })

  test('a per-test override beats the default without disturbing the rest', async ({ page }) => {
    const api = await installApi(page, {
      'GET /api/owner': { success: true, owner: 'someone-else' }
    })
    await page.goto('/')

    const [owner, health] = await page.evaluate(async (url: string) => {
      const a = (await (await fetch(`${url}/owner`)).json()) as { owner: string }
      const b = (await (await fetch(`${url}/healthcheck`)).json()) as { status: string }
      return [a.owner, b.status]
    }, API)

    expect(owner).toBe('someone-else')
    expect(health).toBe('healthy') // still the default
    expect(api.unmocked).toEqual([])
  })

  test('a wildcard entry matches any tail, and the exact entry still wins', async ({ page }) => {
    const api = await installApi(page, {
      'GET /api/temporal/batches': { success: true, batches: ['exact-wins'] }
    })
    await page.goto('/')

    const [wild, exact] = await page.evaluate(async (url: string) => {
      const a = (await (await fetch(`${url}/temporal/batch/some/deep/id`)).json()) as {
        success: boolean
      }
      const b = (await (await fetch(`${url}/temporal/batches`)).json()) as { batches: string[] }
      return [a.success, b.batches]
    }, API)

    expect(wild).toBe(true) // matched 'GET /api/temporal/batch/*'
    expect(exact).toEqual(['exact-wins'])
    expect(api.unmocked).toEqual([])
  })

  test('captures POST bodies so an action can be asserted on', async ({ page }) => {
    const api = await installApi(page)
    await page.goto('/')

    await page.evaluate(async (url: string) => {
      await fetch(`${url}/merge-pr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo: 'a/b', prNumber: 7 })
      })
    }, API)

    const post = api.posts.find(p => p.key === 'POST /api/merge-pr')
    expect(post?.body).toEqual({ repo: 'a/b', prNumber: 7 })
  })
})

test.describe('route table', () => {
  test('covers every endpoint src/api/endpoints.ts can reach', async () => {
    // A cheap guard against the table drifting behind the client. It compares
    // against the paths the endpoints module actually references, so adding an
    // endpoint without a mock fails here rather than in an unrelated spec.
    const { readFileSync } = await import('node:fs')
    const src = readFileSync(new URL('../../src/api/endpoints.ts', import.meta.url), 'utf8')

    // Pull '/api/...' literals, including the static prefix of template literals.
    const referenced = new Set(
      [...src.matchAll(/['"`](\/api\/[^'"`$)]*)/g)]
        .map(m => m[1].replace(/\/$/, ''))
        .filter(p => p.length > '/api/'.length)
    )

    const known = Object.keys(defaultRoutes).map(k => k.split(' ')[1])
    const covered = (path: string) =>
      known.some(k => {
        if (!k.endsWith('/*')) return k === path
        // A parameterised endpoint is written `/api/oss/dossier/${slug}` in the
        // client, so the literal we can extract is the static prefix with its
        // trailing slash stripped. Accept both that and any deeper path.
        const withSlash = k.slice(0, -1) // '/api/oss/dossier/'
        const bare = k.slice(0, -2) // '/api/oss/dossier'
        return path === bare || path.startsWith(withSlash)
      })

    const missing = [...referenced].filter(p => !covered(p)).sort()
    expect(missing, `endpoints with no entry in defaultRoutes: ${missing.join(', ')}`).toEqual([])
  })
})
