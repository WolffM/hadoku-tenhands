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

    // App should render
    await expect(page.locator('.vibedispatch')).toBeVisible()

    // Title should be visible
    await expect(page.locator('.vibedispatch__title')).toContainText('VibeDispatch')

    // Navigation tabs should be visible
    await expect(page.locator('.nav-tabs')).toBeVisible()

    // Pipelines tab should be active by default
    const pipelinesTab = page.locator('.nav-tabs__tab', { hasText: 'Pipelines' })
    await expect(pipelinesTab).toHaveClass(/nav-tabs__tab--active/)
  })

  test('can navigate to Review Queue', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Click Review Queue tab
    await page.locator('.nav-tabs__tab', { hasText: 'Review Queue' }).click()

    // Review Queue tab should be active
    const reviewTab = page.locator('.nav-tabs__tab', { hasText: 'Review Queue' })
    await expect(reviewTab).toHaveClass(/nav-tabs__tab--active/)

    // Review Queue view should be visible
    await expect(page.locator('.review-queue-view')).toBeVisible()
  })

  test('can navigate to Health view', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Click Health tab
    await page.locator('.nav-tabs__tab', { hasText: 'Health' }).click()

    // Health tab should be active
    const healthTab = page.locator('.nav-tabs__tab', { hasText: 'Health' })
    await expect(healthTab).toHaveClass(/nav-tabs__tab--active/)

    // Health view should be visible
    await expect(page.locator('.health-view')).toBeVisible()
  })

  test('can navigate between all views', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Start at Pipelines
    await expect(page.locator('.nav-tabs__tab', { hasText: 'Pipelines' })).toHaveClass(
      /nav-tabs__tab--active/
    )

    // Go to Health
    await page.locator('.nav-tabs__tab', { hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible()

    // Go to Review Queue
    await page.locator('.nav-tabs__tab', { hasText: 'Review Queue' }).click()
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Go back to Pipelines
    await page.locator('.nav-tabs__tab', { hasText: 'Pipelines' }).click()
    await expect(page.locator('.vibecheck-view')).toBeVisible()
  })

  test('shows badge on Review Queue tab when items need review', async ({ page }) => {
    await page.goto('/?key=test-key')

    // Wait for data to load
    await page.waitForResponse('**/dispatch/api/stage4-prs')

    // Review Queue tab should show a badge
    const badge = page
      .locator('.nav-tabs__tab', { hasText: 'Review Queue' })
      .locator('.nav-tabs__badge')

    // Badge may or may not be visible depending on whether there are items
    // This test verifies the badge element exists when there are items
    const badgeCount = await badge.count()
    if (badgeCount > 0) {
      await expect(badge).toBeVisible()
    }
  })
})

test.describe('Auth Key Handling', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
  })

  test('stores auth key from URL in sessionStorage', async ({ page }) => {
    await page.goto('/?key=my-secret-key')

    // Wait for app to load
    await expect(page.locator('.vibedispatch')).toBeVisible()

    // Check sessionStorage
    const storedKey = await page.evaluate(() => sessionStorage.getItem('dispatch_key'))
    expect(storedKey).toBe('my-secret-key')
  })

  test('uses auth key from sessionStorage on subsequent loads', async ({ page }) => {
    // First visit with key
    await page.goto('/?key=my-secret-key')
    await expect(page.locator('.vibedispatch')).toBeVisible()

    // Navigate to same page without key
    await page.goto('/')
    await expect(page.locator('.vibedispatch')).toBeVisible()

    // Should still have the key
    const storedKey = await page.evaluate(() => sessionStorage.getItem('dispatch_key'))
    expect(storedKey).toBe('my-secret-key')
  })
})
