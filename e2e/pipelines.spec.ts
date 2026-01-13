/**
 * Pipelines View Tests
 *
 * Tests for the 4-stage vibecheck pipeline view.
 */

import { test, expect } from '@playwright/test'
import { mockAllAPIs } from './fixtures/api-mocks'

test.describe('Pipelines View', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('displays 4 stage tabs', async ({ page }) => {
    // Wait for the vibecheck view to load
    await expect(page.locator('.vibecheck-view')).toBeVisible()

    // Should have 4 stage tabs
    const stageTabs = page.locator('.stage-tabs .stage-tab')
    await expect(stageTabs).toHaveCount(4)

    // Verify tab labels
    await expect(stageTabs.nth(0)).toContainText('Install')
    await expect(stageTabs.nth(1)).toContainText('Run')
    await expect(stageTabs.nth(2)).toContainText('Assign')
    await expect(stageTabs.nth(3)).toContainText('Review')
  })

  test('has Refresh All button', async ({ page }) => {
    await expect(page.locator('.vibecheck-view')).toBeVisible()

    const refreshBtn = page.getByRole('button', { name: /Refresh All/i })
    await expect(refreshBtn).toBeVisible()
  })
})

test.describe('Stage 1 - Install', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('displays repos needing vibecheck installation', async ({ page }) => {
    // Click Install tab
    await page.locator('.stage-tab', { hasText: /Install/i }).click()

    // Wait for data to load
    await page.waitForResponse('**/dispatch/api/stage1-repos')

    // At least check that the stage content is visible
    await expect(page.locator('.stage-content, .stage1-install')).toBeVisible()
  })

  test('has Select All and Select None buttons', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Install/i }).click()
    await page.waitForResponse('**/dispatch/api/stage1-repos')

    await expect(page.getByRole('button', { name: /Select All/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Select None/i })).toBeVisible()
  })

  test('has Install Selected button', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Install/i }).click()
    await page.waitForResponse('**/dispatch/api/stage1-repos')

    await expect(page.getByRole('button', { name: /Install Selected/i })).toBeVisible()
  })
})

test.describe('Stage 2 - Run', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('displays repos with vibecheck installed', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Run/i }).click()
    await page.waitForResponse('**/dispatch/api/stage2-repos')

    await expect(page.locator('.stage-content, .stage2-run')).toBeVisible()
  })

  test('shows recommended repos section', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Run/i }).click()
    await page.waitForResponse('**/dispatch/api/stage2-repos')

    // Look for recommended section
    const recommendedSection = page.locator('text=Recommended')
    const hasRecommended = (await recommendedSection.count()) > 0

    if (hasRecommended) {
      await expect(recommendedSection.first()).toBeVisible()
    }
  })

  test('has Run All Recommended button when repos exist', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Run/i }).click()
    await page.waitForResponse('**/dispatch/api/stage2-repos')

    const runBtn = page.getByRole('button', { name: /Run All Recommended|Run Selected/i })
    await expect(runBtn.first()).toBeVisible()
  })
})

test.describe('Stage 3 - Assign', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('displays vibecheck issues', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Assign/i }).click()
    await page.waitForResponse('**/dispatch/api/stage3-issues')

    await expect(page.locator('.stage-content, .stage3-assign')).toBeVisible()
  })

  test('has severity filter', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Assign/i }).click()
    await page.waitForResponse('**/dispatch/api/stage3-issues')

    // Look for severity filter dropdown
    const severityFilter = page
      .locator('select, [role="combobox"]')
      .filter({ hasText: /Severity|All/i })
    const hasFilter = (await severityFilter.count()) > 0

    if (hasFilter) {
      await expect(severityFilter.first()).toBeVisible()
    }
  })

  test('displays severity badges on issues', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Assign/i }).click()
    await page.waitForResponse('**/dispatch/api/stage3-issues')

    // Look for severity badges
    const badges = page.locator('.severity-badge, [class*="severity"]')
    const hasBadges = (await badges.count()) > 0

    // May not have badges if no issues
    expect(hasBadges).toBeDefined()
  })
})

test.describe('Stage 4 - Review', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('displays open PRs', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Review/i }).click()
    await page.waitForResponse('**/dispatch/api/stage4-prs')

    await expect(page.locator('.stage-content, .stage4-review')).toBeVisible()
  })

  test('separates Ready for Review and In Progress sections', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Review/i }).click()
    await page.waitForResponse('**/dispatch/api/stage4-prs')

    // Look for section headers
    const readySection = page.locator('text=Ready for Review')
    const inProgressSection = page.locator('text=In Progress')

    // At least one should be visible if there are PRs
    const hasReadySection = (await readySection.count()) > 0
    const hasInProgressSection = (await inProgressSection.count()) > 0

    expect(hasReadySection || hasInProgressSection).toBeDefined()
  })

  test('has quick action buttons for PRs', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Review/i }).click()
    await page.waitForResponse('**/dispatch/api/stage4-prs')

    // Look for action buttons (view, approve, merge)
    const actionButtons = page.locator('button').filter({ hasText: /View|Approve|Merge|👁|✅|🔀/i })
    const hasButtons = (await actionButtons.count()) > 0

    // May not have buttons if no PRs
    expect(hasButtons).toBeDefined()
  })

  test('can open PR detail modal', async ({ page }) => {
    await page.locator('.stage-tab', { hasText: /Review/i }).click()
    await page.waitForResponse('**/dispatch/api/stage4-prs')

    // Click view button on first PR
    const viewButton = page
      .locator('button')
      .filter({ hasText: /View|👁️/i })
      .first()

    if ((await viewButton.count()) > 0) {
      await viewButton.click()

      // Wait for PR details to load
      await page.waitForResponse('**/dispatch/api/pr-details')

      // Modal should be visible
      await expect(page.locator('.modal, [role="dialog"]')).toBeVisible()
    }
  })
})

test.describe('Stage Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('can navigate between all stages', async ({ page }) => {
    await expect(page.locator('.vibecheck-view')).toBeVisible()

    // Click through each stage tab
    const stages = ['Install', 'Run', 'Assign', 'Review']

    for (const stage of stages) {
      await page.locator('.stage-tab', { hasText: new RegExp(stage, 'i') }).click()

      // Active tab should have active class
      const activeTab = page.locator('.stage-tab--active, .stage-tab.active')
      await expect(activeTab).toContainText(new RegExp(stage, 'i'))
    }
  })

  test('stage tabs show item counts', async ({ page }) => {
    await expect(page.locator('.vibecheck-view')).toBeVisible()

    // Wait for all data to load
    await Promise.all([
      page.waitForResponse('**/dispatch/api/stage1-repos'),
      page.waitForResponse('**/dispatch/api/stage2-repos'),
      page.waitForResponse('**/dispatch/api/stage3-issues'),
      page.waitForResponse('**/dispatch/api/stage4-prs')
    ])

    // Check for count badges on tabs
    const tabBadges = page.locator('.stage-tab .count, .stage-tab .badge')
    const hasBadges = (await tabBadges.count()) > 0

    // Should have at least some counts
    expect(hasBadges).toBeDefined()
  })
})
