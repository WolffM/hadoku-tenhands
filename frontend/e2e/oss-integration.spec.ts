/**
 * Real Integration E2E Tests for the OSS Pipeline
 *
 * These tests hit the REAL Flask backend (no route interception).
 * They require:
 * - A running Flask backend on localhost:5000
 * - A valid GitHub token (gh auth login)
 *
 * Skipped in CI environments. Run locally with:
 *   cd frontend && pnpm exec playwright test e2e/oss-integration.spec.ts
 */

import { test, expect } from '@playwright/test'

const BASE_URL = process.env.BACKEND_URL || 'http://localhost:5000'

/* eslint-disable @typescript-eslint/no-unsafe-assignment, @typescript-eslint/no-unsafe-member-access, @typescript-eslint/no-unsafe-argument, @typescript-eslint/no-unsafe-call */

test.describe('OSS Pipeline — Real Integration', () => {
  // Only run when INTEGRATION_TEST=1 is set — requires live backend + GitHub token
  test.skip(!process.env.INTEGRATION_TEST, 'Set INTEGRATION_TEST=1 to run integration tests')

  test.describe.configure({ mode: 'serial' })

  test('debug/gh-health returns authenticated status', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/dispatch/api/oss/debug/gh-health`)
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(data.success).toBe(true)
    expect(data.auth_status).toBeDefined()
    expect(data.user).toBeDefined()
    expect(data.user.login).toBeTruthy()
  })

  test('debug/aggregator-health returns configured status', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/dispatch/api/oss/debug/aggregator-health`)
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(data.success).toBe(true)
    // configured may be true or false depending on env
    expect(typeof data.configured).toBe('boolean')
    if (data.configured) {
      expect(typeof data.reachable).toBe('boolean')
      expect(typeof data.response_time_ms).toBe('number')
    }
  })

  test('debug/state-dump returns readable JSON files', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/dispatch/api/oss/debug/state-dump`)
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(data.success).toBe(true)
    expect(data.files).toBeDefined()
    // All files should be arrays (possibly empty)
    for (const [_name, fileData] of Object.entries(data.files)) {
      expect(Array.isArray((fileData as { data: unknown[] }).data)).toBe(true)
    }
  })

  test('Stage 1: add and remove a test target repo', async ({ request }) => {
    const testSlug = 'octocat/Hello-World'

    // Add the target
    const addResponse = await request.post(`${BASE_URL}/dispatch/api/oss/add-target`, {
      data: { slug: testSlug }
    })
    expect(addResponse.ok()).toBeTruthy()
    const addData = await addResponse.json()
    expect(addData.success).toBe(true)

    // Verify it appears in stage1 data
    const stage1Response = await request.get(`${BASE_URL}/dispatch/api/oss/stage1-targets`)
    expect(stage1Response.ok()).toBeTruthy()
    const stage1Data = await stage1Response.json()
    expect(stage1Data.success).toBe(true)
    expect(stage1Data.targets).toBeDefined()

    const found = stage1Data.targets.some(
      (t: { slug: string }) => t.slug === 'octocat-Hello-World' || t.slug === testSlug
    )
    expect(found).toBe(true)

    // Clean up — remove the target
    const removeResponse = await request.post(`${BASE_URL}/dispatch/api/oss/remove-target`, {
      data: { slug: testSlug }
    })
    expect(removeResponse.ok()).toBeTruthy()
  })

  test('Stage 2: scored issues endpoint works', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/dispatch/api/oss/stage2-issues`)
    expect(response.ok()).toBeTruthy()

    const data = await response.json()
    expect(data.success).toBe(true)
    // Issues may be empty if no targets are watched, that's OK
    expect(Array.isArray(data.issues)).toBe(true)
  })

  test('debug/score-issue returns breakdown for a real issue', async ({ request }) => {
    // Use a well-known public repo issue
    const response = await request.get(
      `${BASE_URL}/dispatch/api/oss/debug/score-issue?owner=octocat&repo=Hello-World&issue_number=1`
    )

    if (response.ok()) {
      const data = await response.json()
      expect(data.success).toBe(true)
      expect(data.breakdown).toBeDefined()
      expect(typeof data.breakdown.final_score).toBe('number')
      expect(data.breakdown.base_score).toBe(50)
    } else {
      // Issue may not exist or API error — just verify we got a structured error
      const data = await response.json()
      expect(data.success).toBe(false)
      expect(data.error).toBeTruthy()
    }
  })

  test('UI loads and shows pipeline selection', async ({ page }) => {
    await page.goto(`${BASE_URL}/?key=test-key`)
    await expect(page.locator('text=VibeDispatch')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
  })

  test('UI: can navigate to OSS pipeline and see stage tabs', async ({ page }) => {
    await page.goto(`${BASE_URL}/?key=test-key`)
    await expect(page.locator('text=Select a Pipeline')).toBeVisible({ timeout: 15000 })

    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()

    // All 5 stage tabs should be visible
    const stageLabels = [
      'Target Repos',
      'Select Issues',
      'Fork & Assign',
      'Review on Fork',
      'Submit Upstream'
    ]
    for (const label of stageLabels) {
      await expect(page.locator('.stage-tab__label').filter({ hasText: label })).toBeVisible()
    }
  })
})
