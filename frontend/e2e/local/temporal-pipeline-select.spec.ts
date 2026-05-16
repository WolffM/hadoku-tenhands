/**
 * Crimson-Kitty pipeline-select + main view integration.
 *
 * Covers phase-1-plan.md step 2.7:
 *   - PipelineSelectView shows 3 tiles (vibecheck / oss / crimson-kitty)
 *   - clicking the crimson-kitty tile navigates to the temporal view
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'
import { mockTemporalAPIs } from '../fixtures/temporal-mocks'

test.describe('Temporal pipeline select', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await mockTemporalAPIs(page)
  })

  test('picker shows 3 tiles', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    const cards = page.locator('.pipeline-select-card')
    await expect(cards).toHaveCount(3)
    await expect(cards.filter({ hasText: 'Vibecheck Pipeline' })).toBeVisible()
    await expect(cards.filter({ hasText: 'OSS Contribution Pipeline' })).toBeVisible()
    await expect(cards.filter({ hasText: 'Crimson-Kitty' })).toBeVisible()
  })

  test('clicking crimson-kitty tile navigates to temporal view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await page.locator('.pipeline-select-card').filter({ hasText: 'Crimson-Kitty' }).click()

    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()
    await expect(page.getByTestId('temporal-pipeline-view')).toBeVisible()
    // Tab bar is present; the Inbox tab is the default landing surface.
    await expect(page.getByTestId('temporal-tabs')).toBeVisible()
    await expect(page.getByTestId('temporal-inbox')).toBeVisible()
    // The batches pane lives on the Active tab.
    await page.getByTestId('temporal-tab-active').click()
    await expect(page.getByTestId('temporal-batches-pane')).toBeVisible()
  })

  test('Home → Crimson-Kitty card switches into the view from another pipeline', async ({
    page
  }) => {
    await page.goto('/?key=test-key')
    // Enter Vibecheck first
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Pipelines are no longer surfaced as top-level nav tabs — Home is the
    // pipeline-switching surface. Click Home, then click the Crimson-Kitty card.
    await page.getByRole('button', { name: /^Home$/i }).click()
    await page.locator('.pipeline-select-card').filter({ hasText: 'Crimson-Kitty' }).click()
    await expect(page.getByTestId('temporal-pipeline-view')).toBeVisible()
  })
})
