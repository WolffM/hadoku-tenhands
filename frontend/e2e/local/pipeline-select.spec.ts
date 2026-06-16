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

    await expect(page.locator('text=TenHands')).toBeVisible()
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

  test('top nav has exactly three tabs (Home, Retrospective, Health)', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // The fixed three top tabs
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: /^Home$/ })).toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /^Retrospective$/ })
    ).toBeVisible()
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: /^Health$/ })).toBeVisible()

    // Removed (cleanup 2026-04-30): pipeline-specific tabs and Review Queue
    // are no longer surfaced as top-level tabs. Pipelines are entered via
    // Home cards; Review Queue data lives inside the Vibecheck pipeline.
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /^Pipelines$/ })
    ).not.toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /^OSS Contrib$/ })
    ).not.toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /^Crimson-Kitty$/ })
    ).not.toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /Review Queue/ })
    ).not.toBeVisible()
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

  test('can switch between pipelines via Home', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Enter Vibecheck
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Click Home → land on picker → click OSS card
    await page.getByRole('button', { name: /^Home$/i }).click()
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Fork & Assign' })
    ).toBeVisible()

    // Home again → click Vibecheck
    await page.getByRole('button', { name: /^Home$/i }).click()
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
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
})
