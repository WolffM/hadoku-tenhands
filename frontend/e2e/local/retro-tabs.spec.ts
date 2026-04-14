/**
 * RetroView tab-strip e2e (phase-1-plan.md step 2.8).
 *
 *   - The tab strip renders Legacy + Temporal tabs
 *   - Default tab is Legacy and loads legacy batches
 *   - Clicking the Temporal tab loads crimson-kitty batches, lazily
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'
import { mockTemporalAPIs, mockTemporalBatches } from '../fixtures/temporal-mocks'

test.describe('Retro view tabs', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await mockTemporalAPIs(page)
    await page.goto('/?key=test-key')
    // Enter any pipeline so the retrospective nav tab is visible
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await page.getByRole('button', { name: /Retrospective/i }).click()
  })

  test('tab strip renders both tabs', async ({ page }) => {
    await expect(page.getByTestId('retro-tab-strip')).toBeVisible()
    await expect(page.getByTestId('retro-tab-legacy')).toBeVisible()
    await expect(page.getByTestId('retro-tab-temporal')).toBeVisible()
  })

  test('default tab is Legacy', async ({ page }) => {
    await expect(page.getByTestId('retro-tab-content-legacy')).toBeVisible()
    await expect(page.getByTestId('retro-tab-content-temporal')).toHaveCount(0)
  })

  test('clicking Temporal tab loads temporal batches', async ({ page }) => {
    await page.getByTestId('retro-tab-temporal').click()
    await expect(page.getByTestId('retro-tab-content-temporal')).toBeVisible()
    await expect(page.getByTestId('retro-tab-content-legacy')).toHaveCount(0)

    const buttons = page.getByTestId('retro-temporal-batch-button')
    await expect(buttons).toHaveCount(mockTemporalBatches.length)
    await expect(buttons.first()).toContainText(mockTemporalBatches[0].batch_id)

    // Drill into one batch
    await buttons.first().click()
    await expect(page.getByTestId('retro-temporal-issues')).toBeVisible()
    await expect(page.getByTestId('retro-temporal-issue').first()).toBeVisible()
  })
})
