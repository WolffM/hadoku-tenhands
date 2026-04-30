/**
 * Navigation Tests
 *
 * Tests for navigating between views in VibeDispatch.
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'

test.describe('Navigation', () => {
  test.beforeEach(async ({ page }) => {
    // Set up API mocks before each test
    await mockAllAPIs(page)
  })

  test('loads the app with pipeline selection view by default', async ({ page }) => {
    await page.goto('/?key=test-key')

    // App should render - look for the title
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Pipeline selection should be visible
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await expect(page.locator('text=Vibecheck Pipeline')).toBeVisible()
    await expect(page.locator('text=OSS Contribution Pipeline')).toBeVisible()
  })

  test('can navigate to Pipelines view via card', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()

    // Click the Vibecheck Pipeline card
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()

    // Stage tabs should be visible
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
  })

  test('can navigate to Health view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Click Health nav tab (use specific selector to avoid matching OSS "Repo Health" card)
    await page
      .locator('.nav-tabs__tab')
      .filter({ hasText: /^Health$/ })
      .click()

    // Pipeline selection should disappear
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()

    // Health nav tab should still be visible
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: /^Health$/ })).toBeVisible()
  })

  test('can navigate between Home and Health', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Go to a pipeline first via card so we have view-state to navigate away from
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Go to Health via top tab
    await page
      .locator('.nav-tabs__tab')
      .filter({ hasText: /^Health$/ })
      .click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).not.toBeVisible()

    // Go back to Home (pipeline picker) via top tab
    await page.getByRole('button', { name: /^Home$/i }).click()
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
  })

  test('Home button returns to pipeline selection', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Navigate to Pipelines
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Click Home
    await page.getByRole('button', { name: /Home/i }).click()

    // Should be back at pipeline selection
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
  })
})

test.describe('Auth Key Handling', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
  })

  test('stores auth key from URL in sessionStorage', async ({ page }) => {
    await page.goto('/?key=my-secret-key')

    // Wait for app to load
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Check sessionStorage
    const storedKey = await page.evaluate(() => sessionStorage.getItem('dispatch_key'))
    expect(storedKey).toBe('my-secret-key')
  })

  test('uses auth key from sessionStorage on subsequent loads', async ({ page }) => {
    // First visit with key
    await page.goto('/?key=my-secret-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Navigate to same page without key
    await page.goto('/')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Should still have the key
    const storedKey = await page.evaluate(() => sessionStorage.getItem('dispatch_key'))
    expect(storedKey).toBe('my-secret-key')
  })
})
