/**
 * Health View Tests
 *
 * Tests for the Health Check view showing workflow status.
 */

import { test, expect } from '@playwright/test'
import { mockAllAPIs } from './fixtures/api-mocks'

test.describe('Health View', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    // Navigate to Health view
    await page.getByRole('button', { name: /Health/i }).click()
  })

  test('displays health check title and subtitle', async ({ page }) => {
    await expect(page.locator('text=Health Check')).toBeVisible()
    await expect(page.locator('text=Monitor workflow status')).toBeVisible()
  })

  test('displays stats cards', async ({ page }) => {
    // Wait for data to load
    await expect(page.locator('.stat-card').first()).toBeVisible()

    // Should have 4 stat cards: Total, Successful, Failed, In Progress
    const statCards = page.locator('.stat-card')
    await expect(statCards).toHaveCount(4)

    // Check labels exist (use specific selectors to avoid ambiguity)
    await expect(page.locator('.stat-card__label:has-text("Total Runs")')).toBeVisible()
    await expect(page.locator('.stat-card__label:has-text("Successful")')).toBeVisible()
    await expect(page.locator('.stat-card__label:has-text("Failed")')).toBeVisible()
    await expect(page.locator('.stat-card__label:has-text("In Progress")')).toBeVisible()
  })

  test('displays workflow runs table', async ({ page }) => {
    // Wait for table to appear
    await expect(page.locator('.data-table')).toBeVisible()

    // Check table headers
    await expect(page.locator('th:has-text("Repository")')).toBeVisible()
    await expect(page.locator('th:has-text("Workflow")')).toBeVisible()
    await expect(page.locator('th:has-text("Status")')).toBeVisible()
  })

  test('displays workflow run data from mock', async ({ page }) => {
    // Wait for table to load with mock data
    await expect(page.locator('text=repo-with-vc-1').first()).toBeVisible()

    // Check for workflow names from mock data
    await expect(page.locator('text=vibeCheck').first()).toBeVisible()
  })

  test('has refresh button', async ({ page }) => {
    const refreshBtn = page.getByRole('button', { name: /Refresh/i })
    await expect(refreshBtn).toBeVisible()
  })

  test('has filter controls', async ({ page }) => {
    // Check for filter section header
    await expect(page.locator('.filter-card__header')).toBeVisible()

    // Check for filter dropdowns by their labels
    await expect(page.locator('.filter-label:has-text("VibeCheck Status")')).toBeVisible()
    await expect(page.locator('.filter-label:has-text("Run Status")')).toBeVisible()
    await expect(page.locator('.filter-label:has-text("Workflow Name")')).toBeVisible()
  })

  test('has Show Failed quick filter button', async ({ page }) => {
    const showFailedBtn = page.getByRole('button', { name: /Show Failed/i })
    await expect(showFailedBtn).toBeVisible()
  })

  test('displays API health status', async ({ page }) => {
    // Wait for health data to load
    await expect(page.locator('text=healthy')).toBeVisible()

    // Check for owner and API version
    await expect(page.locator('text=Owner:')).toBeVisible()
    await expect(page.locator('text=test-user')).toBeVisible()
  })
})

test.describe('Health View Filters', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await page.getByRole('button', { name: /Health/i }).click()
  })

  test('can filter by VibeCheck status', async ({ page }) => {
    // Wait for table to load
    await expect(page.locator('.data-table')).toBeVisible()

    // Find and interact with VC filter
    const vcFilter = page
      .locator('select')
      .filter({ hasText: /All Repos/i })
      .first()
    await expect(vcFilter).toBeVisible()
  })

  test('can filter by run status', async ({ page }) => {
    // Wait for table to load
    await expect(page.locator('.data-table')).toBeVisible()

    // Find status filter dropdown
    const statusFilter = page
      .locator('select')
      .filter({ hasText: /All Status/i })
      .first()
    await expect(statusFilter).toBeVisible()
  })

  test('Show Failed button changes filter', async ({ page }) => {
    // Wait for table to load
    await expect(page.locator('.data-table')).toBeVisible()

    // Click Show Failed
    await page.getByRole('button', { name: /Show Failed/i }).click()

    // Status filter should now show Failed
    const statusFilter = page.locator('select.filter-select').nth(1)
    await expect(statusFilter).toHaveValue('failure')
  })
})

test.describe('Health View Loading States', () => {
  test('shows loading state initially', async ({ page }) => {
    // Set up a delayed response to catch loading state
    await page.route('**/dispatch/api/global-workflow-runs', async route => {
      await new Promise(resolve => setTimeout(resolve, 500))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          runs: [],
          owner: 'test-user'
        })
      })
    })

    await page.route('**/dispatch/api/healthcheck', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          status: 'healthy',
          owner: 'test-user',
          api_version: '2.0.0'
        })
      })
    })

    await page.goto('/?key=test-key')
    await page.getByRole('button', { name: /Health/i }).click()

    // Should show refreshing state on button
    await expect(page.getByRole('button', { name: /Refreshing/i })).toBeVisible()
  })
})
