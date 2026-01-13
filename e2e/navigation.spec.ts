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

  test('loads the app with Pipelines view by default', async ({ page }) => {
    await page.goto('/?key=test-key')

    // App should render - look for the title
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Pipelines button should be visible
    const pipelinesBtn = page.getByRole('button', { name: /Pipelines/i })
    await expect(pipelinesBtn).toBeVisible()

    // Stage tabs should be visible (Install VibeCheck, Run VibeCheck, etc.)
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
  })

  test('can navigate to Review Queue', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Verify Review Queue button exists
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    await expect(reviewQueueBtn).toBeVisible()

    // Click it
    await reviewQueueBtn.click()

    // Stage tabs should disappear (view switched)
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).not.toBeVisible({
      timeout: 5000
    })
  })

  test('can navigate to Health view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Click Health button
    await page.getByRole('button', { name: /Health/i }).click()

    // Stage tabs should disappear (we're no longer in Pipelines view)
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).not.toBeVisible()

    // Health button should still be visible
    await expect(page.getByRole('button', { name: /Health/i })).toBeVisible()
  })

  test('can navigate between Pipelines and Health', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Start at Pipelines - verify stage tabs are visible
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()

    // Go to Health
    await page.getByRole('button', { name: /Health/i }).click()
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).not.toBeVisible()

    // Go back to Pipelines
    await page.getByRole('button', { name: /Pipelines/i }).click()

    // Should see stage tabs again
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
  })

  test('shows badge on Review Queue tab when items need review', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Wait for app to load
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Review Queue button should show a badge with count
    // The badge appears as part of the button text like "Review Queue 4"
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    await expect(reviewQueueBtn).toBeVisible()

    // Check if the button text contains a number (the badge count)
    const buttonText = await reviewQueueBtn.textContent()
    expect(buttonText).toMatch(/Review Queue.*\d+/)
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
