/**
 * Review Queue Tests
 *
 * Tests for the Review Queue view functionality.
 */

import { test, expect } from '@playwright/test'
import { mockAllAPIs } from './fixtures/api-mocks'

test.describe('Review Queue View', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
  })

  test('can navigate to Review Queue without errors', async ({ page }) => {
    // Set up console error listener BEFORE navigation
    const errors: string[] = []
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text())
      }
    })

    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Click Review Queue tab
    await page.getByRole('button', { name: /Review Queue/i }).click()

    // Wait for view to load - check for the review queue view element
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Page should still be responsive - title should remain visible
    await expect(page.locator('.vibedispatch__title')).toBeVisible()

    // Should not have infinite loop error
    const hasInfiniteLoopError = errors.some(e => e.includes('Maximum update depth'))
    expect(hasInfiniteLoopError).toBeFalsy()
  })

  test('displays empty state or carousel based on data', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Navigate to Review Queue
    await page.getByRole('button', { name: /Review Queue/i }).click()

    // Wait for view to load
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Should show either carousel content or empty state
    // The mock data has PR 101 (non-draft, not approved) which should appear in review queue
    // Use first() since loading state may also be visible inside the carousel
    await expect(
      page.locator('.review-carousel-header').or(page.locator('.review-carousel-empty')).first()
    ).toBeVisible({ timeout: 10000 })
  })

  test('can navigate back to Pipelines from Review Queue', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Go to Review Queue
    await page.getByRole('button', { name: /Review Queue/i }).click()
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Go back to Pipelines
    await page.getByRole('button', { name: /Pipelines/i }).click()

    // Should see stage tabs again
    await expect(page.getByRole('button', { name: /Install VibeCheck/i })).toBeVisible()
  })

  test('Review Queue tab shows badge with count', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // The Review Queue button should be visible and have some content
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    await expect(reviewQueueBtn).toBeVisible()

    // Badge should have a number (the count of items needing review)
    const buttonText = await reviewQueueBtn.textContent()
    expect(buttonText).toBeTruthy()
  })
})

test.describe('Review Queue Empty State', () => {
  test('shows empty state when no PRs need review', async ({ page }) => {
    // Override mock to return only draft PRs (which don't need review)
    await page.route('**/dispatch/api/stage4-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          owner: 'test-user',
          prs: [
            {
              number: 1,
              title: 'Draft PR',
              repo: 'test-repo',
              author: { login: 'copilot[bot]' },
              isDraft: true,
              copilotCompleted: false,
              reviewDecision: null,
              headRefName: 'fix/test',
              baseRefName: 'main',
              createdAt: new Date().toISOString()
            }
          ]
        })
      })
    })

    // Set up other required mocks
    await page.route('**/dispatch/api/owner', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: 'test-user' })
      })
    })

    await page.route('**/dispatch/api/stage1-repos', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: 'test-user', repos: [] })
      })
    })

    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Navigate to Review Queue
    await page.getByRole('button', { name: /Review Queue/i }).click()

    // Wait for view to render
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Should eventually show empty state (no items to review since only draft PRs)
    await expect(page.locator('text=No items to review')).toBeVisible({ timeout: 10000 })
  })

  test('excludes demo-labeled PRs from review queue', async ({ page }) => {
    // Mock stage4-prs to return a mix of demo and non-demo PRs
    await page.route('**/dispatch/api/stage4-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          owner: 'test-user',
          prs: [
            {
              number: 200,
              title: 'Non-demo PR ready for review',
              repo: 'test-repo',
              author: { login: 'test-user' },
              isDraft: false,
              copilotCompleted: null,
              reviewDecision: null,
              headRefName: 'feature/important',
              baseRefName: 'main',
              createdAt: new Date().toISOString(),
              labels: []
            },
            {
              number: 201,
              title: 'Demo PR - should not appear',
              repo: 'test-repo',
              author: { login: 'copilot[bot]' },
              isDraft: false,
              copilotCompleted: true,
              reviewDecision: null,
              headRefName: 'demo/test',
              baseRefName: 'main',
              createdAt: new Date().toISOString(),
              labels: [{ name: 'demo' }]
            }
          ]
        })
      })
    })

    // Set up other required mocks
    await page.route('**/dispatch/api/owner', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: 'test-user' })
      })
    })

    await page.route('**/dispatch/api/stage1-repos', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: 'test-user', repos: [] })
      })
    })

    await page.route('**/dispatch/api/stage3-issues', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          owner: 'test-user',
          issues: [],
          labels: [],
          repos_with_copilot_prs: []
        })
      })
    })

    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Navigate to Review Queue
    await page.getByRole('button', { name: /Review Queue/i }).click()

    // Wait for view to render
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Should show the review carousel header (since we have 1 non-demo PR ready for review)
    await expect(page.locator('.review-carousel-header'))
      .toBeVisible({ timeout: 10000 })

    // The Review Queue badge should show count of 1 (only non-demo PR)
    const reviewQueueBtn = page.getByRole('button', { name: /Review Queue/i })
    const buttonText = await reviewQueueBtn.textContent()
    // Badge should show "1" for the single non-demo PR (not "2" which would include demo)
    expect(buttonText).toContain('1')
  })
})

test.describe('Review Queue Error Handling', () => {
  test('handles API error gracefully', async ({ page }) => {
    // Mock API error for stage4
    await page.route('**/dispatch/api/stage4-prs', async route => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ success: false, error: 'Server error' })
      })
    })

    await page.route('**/dispatch/api/owner', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: 'test-user' })
      })
    })

    await page.route('**/dispatch/api/stage1-repos', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: 'test-user', repos: [] })
      })
    })

    await page.goto('/?key=test-key')
    await expect(page.locator('text=VibeDispatch')).toBeVisible()

    // Navigate to Review Queue
    await page.getByRole('button', { name: /Review Queue/i }).click()

    // View should still render (not crash)
    await expect(page.locator('.review-queue-view')).toBeVisible()

    // Page should not crash - title should still be visible
    await expect(page.locator('.vibedispatch__title')).toBeVisible()
  })
})
