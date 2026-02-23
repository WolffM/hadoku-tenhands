/**
 * Navigation Tests
 *
 * Tests for navigating between views in VibeDispatch.
 */

import { test, expect } from '@playwright/test'
import { mockAllAPIs } from './fixtures/api-mocks'

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

  test('can navigate to Review Queue', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Verify Review Queue button exists (visible from select view)
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    await expect(reviewQueueBtn).toBeVisible()

    // Click it
    await reviewQueueBtn.click()

    // Pipeline selection should disappear
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible({ timeout: 5000 })
  })

  test('can navigate to Health view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Click Health button
    await page.getByRole('button', { name: /Health/i }).click()

    // Pipeline selection should disappear
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible()

    // Health button should still be visible
    await expect(page.getByRole('button', { name: /Health/i })).toBeVisible()
  })

  test('can navigate between Pipelines and Health', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Navigate to Pipelines first via card
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Go to Health
    await page.getByRole('button', { name: /Health/i }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).not.toBeVisible()

    // Go back to Pipelines via the Pipelines tab (visible since Health is a global view)
    await page.getByRole('button', { name: /Pipelines/i }).click()

    // Should see stage tabs again
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
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

  test('shows badge on Review Queue tab when items need review', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Navigate to Pipelines so all tabs load data
    await page.locator('.pipeline-select-card').filter({ hasText: 'Vibecheck Pipeline' }).click()

    // Wait for app to load
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Review Queue button should show a badge with count
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    await expect(reviewQueueBtn).toBeVisible()

    // Wait for the badge count to appear (stage 4 data needs to load)
    await expect(async () => {
      const buttonText = await reviewQueueBtn.textContent()
      expect(buttonText).toMatch(/Review Queue.*\d+/)
    }).toPass({ timeout: 5000 })
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
