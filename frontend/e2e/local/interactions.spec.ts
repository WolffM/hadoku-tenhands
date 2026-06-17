/**
 * Button Interaction Tests for the Vibecheck Pipeline
 *
 * Verifies that clicking action buttons (Install, Run, Assign, Approve, Merge)
 * actually triggers the correct API calls with the correct request body.
 *
 * This fills the gap where pipelines.spec.ts only tests display but never
 * verifies button-to-API-call connections.
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'

test.describe('Vibecheck Pipeline — Button Interactions', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    // Navigate from pipeline selection to Vibecheck pipeline
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
  })

  // ============ Stage 1: Install VibeCheck ============

  test('Stage 1: Select All selects all repo checkboxes', async ({ page }) => {
    // Stage 1 is the default tab within vibecheck
    await expect(page.getByRole('checkbox', { name: /repo-without-vc-1/i })).toBeVisible()
    await page.getByRole('button', { name: /Select All/i }).click()

    await expect(page.getByRole('checkbox', { name: /repo-without-vc-1/i })).toBeChecked()
    await expect(page.getByRole('checkbox', { name: /repo-without-vc-2/i })).toBeChecked()
    await expect(page.getByRole('checkbox', { name: /repo-without-vc-3/i })).toBeChecked()
  })

  test('Stage 1: Install Selected triggers install-vibecheck API', async ({ page }) => {
    await expect(page.getByRole('checkbox', { name: /repo-without-vc-1/i })).toBeVisible()

    // Select one repo
    await page.getByRole('checkbox', { name: /repo-without-vc-1/i }).check()

    // Click Install Selected and verify API call
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/install-vibecheck') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Install Selected/i }).click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.owner).toBe('test-user')
    expect(body.repo).toBe('repo-without-vc-1')
  })

  // ============ Stage 2: Run VibeCheck ============

  test('Stage 2: Run button triggers run-vibecheck API', async ({ page }) => {
    // Navigate to Stage 2
    await page.getByRole('button', { name: /Run VibeCheck/i }).click()
    await expect(page.locator('text=repo-with-vc-1').first()).toBeVisible()

    // Click the per-row run button
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/run-vibecheck') && req.method() === 'POST'
      ),
      // The run button uses a play emoji — find it via the button class
      page.locator('.btn--ghost').filter({ hasText: /▶/ }).first().click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.owner).toBe('test-user')
    expect(body.repo).toBeTruthy()
  })

  // ============ Stage 3: Assign Copilot ============

  test('Stage 3: Assign Selected triggers assign-copilot API', async ({ page }) => {
    await page.getByRole('button', { name: /Assign Copilot/i }).click()
    await expect(page.locator('text=Security vulnerability').first()).toBeVisible()

    // Select an issue via checkbox
    const checkbox = page.locator('input[type="checkbox"]').first()
    await checkbox.check()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/assign-copilot') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /Assign Selected|Assign Recommended/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.owner).toBe('test-user')
    expect(body.issue_number).toBeTruthy()
  })

  // ============ Stage 4: Review & Merge ============

  test('Stage 4: View opens modal, Approve triggers approve-pr API', async ({ page }) => {
    await page.getByRole('button', { name: /Review & Merge/i }).click()
    await expect(page.locator('text=Fix security vulnerability').first()).toBeVisible()

    // Open modal via View button (eye emoji)
    await page.locator('.pr-actions .btn--ghost').first().click()
    await expect(page.locator('.modal')).toBeVisible()

    // Wait for PR details to load (title replaces "Loading...")
    await expect(
      page.locator('.modal__title', { hasText: 'Fix security vulnerability in auth module' })
    ).toBeVisible({ timeout: 5000 })

    // Click Approve in modal footer (wait for button to be enabled)
    const approveBtn = page.locator('.modal__footer .btn--success')
    await expect(approveBtn).toBeEnabled()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/approve-pr') && req.method() === 'POST'
      ),
      approveBtn.click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.owner).toBe('test-user')
    expect(body.repo).toBe('repo-with-vc-1')
    expect(body.pr_number).toBe(101)
  })

  test('Stage 4: View opens modal, Merge triggers merge-pr API', async ({ page }) => {
    await page.getByRole('button', { name: /Review & Merge/i }).click()
    await expect(page.locator('text=Fix security vulnerability').first()).toBeVisible()

    // Open modal via View button (eye emoji)
    await page.locator('.pr-actions .btn--ghost').first().click()
    await expect(page.locator('.modal')).toBeVisible()

    // Wait for PR details to load
    await expect(
      page.locator('.modal__title', { hasText: 'Fix security vulnerability in auth module' })
    ).toBeVisible({ timeout: 5000 })

    // Click Merge in modal footer (wait for button to be enabled)
    const mergeBtn = page.locator('.modal__footer .btn--primary')
    await expect(mergeBtn).toBeEnabled()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/merge-pr') && req.method() === 'POST'
      ),
      mergeBtn.click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.owner).toBe('test-user')
    expect(body.repo).toBe('repo-with-vc-1')
    expect(body.pr_number).toBe(101)
  })

  test('Stage 4: Approve via table row button', async ({ page }) => {
    await page.getByRole('button', { name: /Review & Merge/i }).click()
    await expect(page.locator('text=Fix security vulnerability').first()).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/approve-pr') && req.method() === 'POST'
      ),
      page.locator('.btn--ghost').filter({ hasText: /✅/ }).first().click()
    ])

    expect((request.postDataJSON() as Record<string, unknown>).pr_number).toBe(101)
  })

  test('Stage 4: Merge via table row button', async ({ page }) => {
    await page.getByRole('button', { name: /Review & Merge/i }).click()
    await expect(page.locator('text=Fix security vulnerability').first()).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/merge-pr') && req.method() === 'POST'
      ),
      page.locator('.btn--ghost').filter({ hasText: /🔀/ }).first().click()
    ])

    expect((request.postDataJSON() as Record<string, unknown>).pr_number).toBe(101)
  })
})
