/**
 * Pipeline Selection View Tests
 *
 * Tests for the pipeline selection landing page that lets users
 * choose between Vibecheck and OSS Contribution pipelines.
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'

test.describe('Pipeline Selection View', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
  })

  test('loads with pipeline selection as default view', async ({ page }) => {
    await page.goto('/?key=test-key')

    await expect(page.locator('text=VibeDispatch')).toBeVisible()
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
  })

  test('displays two pipeline cards', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Both pipeline cards should be visible
    await expect(
      page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' })
    ).toBeVisible()
    await expect(
      page.locator('.pipeline-select-card').filter({ hasText: 'OSS Contribution Pipeline' })
    ).toBeVisible()
  })

  test('pipeline cards show descriptions', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Vibecheck card has description
    await expect(page.locator('text=Install, run, assign, and review')).toBeVisible()
    // OSS card has description
    await expect(page.locator('text=Repo health, issue selection, pipeline runs')).toBeVisible()
  })

  test('pipeline cards show stage labels', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Vibecheck pipeline stages — use stage span selector to avoid matching description
    const vibecheckStages = page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'Vibecheck Pipeline' })
      .locator('.pipeline-select-card__stage')
    await expect(vibecheckStages.filter({ hasText: 'Install VibeCheck' })).toBeVisible()
    await expect(vibecheckStages.filter({ hasText: 'Run VibeCheck' })).toBeVisible()
    await expect(vibecheckStages.filter({ hasText: 'Assign Copilot' })).toBeVisible()
    await expect(vibecheckStages.filter({ hasText: 'Review & Merge' })).toBeVisible()

    // OSS pipeline stages
    const ossStages = page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .locator('.pipeline-select-card__stage')
    await expect(ossStages.filter({ hasText: 'Repo Health' })).toBeVisible()
    await expect(ossStages.filter({ hasText: 'Fork & Assign' })).toBeVisible()
    await expect(ossStages.filter({ hasText: 'Pipeline Runs' })).toBeVisible()
    await expect(ossStages.filter({ hasText: 'Review' })).toBeVisible()
  })

  test('clicking Vibecheck card navigates to vibecheck view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()

    // Pipeline selection should be gone
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()
    // Vibecheck stage tabs should be visible
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Run VibeCheck/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Assign Copilot/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Review & Merge/i })).toBeVisible()
  })

  test('clicking OSS card navigates to OSS view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()

    // Pipeline selection should be gone
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()
    // OSS stage tabs should be visible (4-tab redesign)
    await expect(page.locator('.stage-tab__label').filter({ hasText: 'Repo Health' })).toBeVisible()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Fork & Assign' })
    ).toBeVisible()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible()
    await expect(page.locator('.stage-tab__label').filter({ hasText: 'Review' })).toBeVisible()
  })

  test('only global tabs visible on select view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Global tabs should be visible
    await expect(page.getByRole('button', { name: /Review Queue/i })).toBeVisible()
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: /^Health$/ })).toBeVisible()

    // Pipeline-specific nav tabs should NOT be visible (use nav-tabs__tab selector to avoid matching pipeline cards)
    await expect(page.locator('.nav-tabs__tab--home')).not.toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /^Pipelines$/ })
    ).not.toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /^OSS Contrib$/ })
    ).not.toBeVisible()
  })

  test('pipeline tabs appear after selecting a pipeline', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Select vibecheck pipeline
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()

    // Now pipeline tabs + Home should appear
    await expect(page.getByRole('button', { name: /^Home$/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Pipelines$/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /OSS Contrib/i })).toBeVisible()
  })

  test('Home button returns to pipeline selection', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Navigate to a pipeline
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Click Home
    await page.getByRole('button', { name: /^Home$/i }).click()

    // Should be back at pipeline selection
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
  })

  test('can switch between pipelines via nav tabs', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Go to Vibecheck
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Switch to OSS via nav tab
    await page.getByRole('button', { name: /OSS Contrib/i }).click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Fork & Assign' })
    ).toBeVisible()

    // Switch back to Vibecheck via nav tab
    await page.getByRole('button', { name: /^Pipelines$/i }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
  })

  test('Review Queue accessible from pipeline selection', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Click Review Queue
    await page.getByRole('button', { name: /Review Queue/i }).click()

    // Pipeline selection should be gone
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()
    // Review Queue view should load
    await expect(page.locator('.review-queue-view')).toBeVisible()
  })

  test('Health accessible from pipeline selection', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Click Health (use nav-tabs selector to avoid matching OSS card containing "Repo Health")
    await page
      .locator('.nav-tabs__tab')
      .filter({ hasText: /^Health$/ })
      .click()

    // Pipeline selection should be gone
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()
    // Health view should load
    await expect(page.locator('text=Health Check')).toBeVisible()
  })

  test('Review Queue badge shows after pipeline data loads', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Enter vibecheck pipeline to trigger data loading
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Badge should appear after stage4 data loads
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    await expect(async () => {
      const buttonText = await reviewQueueBtn.textContent()
      expect(buttonText).toMatch(/Review Queue.*\d+/)
    }).toPass({ timeout: 5000 })

    // Go back to selection view — badge should persist
    await page.getByRole('button', { name: /^Home$/i }).click()
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await expect(async () => {
      const buttonText = await reviewQueueBtn.textContent()
      expect(buttonText).toMatch(/Review Queue.*\d+/)
    }).toPass({ timeout: 5000 })
  })
})
