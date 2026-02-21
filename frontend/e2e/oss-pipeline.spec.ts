/**
 * E2E Tests for the OSS Contribution Pipeline (5 stages)
 *
 * Tests navigation, data display, form submissions, button interactions,
 * and empty states across all OSS pipeline stages.
 */

import { test, expect, type Page } from '@playwright/test'
import { mockAllAPIs, mockOwner } from './fixtures/api-mocks'

/** Navigate to a specific OSS pipeline stage tab */
async function navigateToOSSStage(page: Page, stageLabel: string): Promise<void> {
  // Click "OSS Contrib" in main navigation
  await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()
  // Wait for stage tabs to render (default is "Fork & Assign")
  await expect(page.locator('.stage-tab__label').filter({ hasText: 'Fork & Assign' })).toBeVisible()
  if (stageLabel !== 'Fork & Assign') {
    await page.locator('.stage-tab').filter({ hasText: stageLabel }).click()
  }
}

// ============ Stage 1: Target Repos ============

test.describe('OSS Pipeline - Stage 1: Target Repos', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Target Repos')
  })

  test('displays target repos in table', async ({ page }) => {
    await expect(page.locator('text=fastify-fastify').first()).toBeVisible()
    await expect(page.locator('text=vercel-next.js').first()).toBeVisible()
  })

  test('shows health score badge for repos with health data', async ({ page }) => {
    // fastify-fastify has health.overallViability = 82
    await expect(page.locator('.badge').filter({ hasText: '82' })).toBeVisible()
  })

  test('shows repo metadata columns', async ({ page }) => {
    await expect(page.locator('text=JavaScript').first()).toBeVisible()
    await expect(page.locator('text=TypeScript').first()).toBeVisible()
  })

  test('add target: fills form and submits, verifies API called', async ({ page }) => {
    const input = page.locator('input[placeholder*="fastify/fastify"]')
    await input.fill('lodash/lodash')

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/add-target') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Add Target/i }).click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.slug).toBe('lodash/lodash')
  })

  test('add target: button disabled when slug has no slash', async ({ page }) => {
    const input = page.locator('input[placeholder*="fastify/fastify"]')
    await input.fill('invalid-no-slash')
    const button = page.getByRole('button', { name: /Add Target/i })
    await expect(button).toBeDisabled()
  })

  test('remove target: clicking Remove triggers API call', async ({ page }) => {
    await expect(page.locator('text=fastify-fastify').first()).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/remove-target') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^Remove$/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.slug).toBeTruthy()
  })

  test('refresh target: clicking Refresh triggers API call', async ({ page }) => {
    await expect(page.locator('text=fastify-fastify').first()).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/refresh-target') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^Refresh$/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.slug).toBeTruthy()
  })

  test('empty state when no targets', async ({ page }) => {
    await page.route('**/dispatch/api/oss/stage1-targets', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, targets: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Target Repos')
    await expect(page.locator('text=No target repos')).toBeVisible()
  })
})

// ============ Stage 2: Select Issues ============

test.describe('OSS Pipeline - Stage 2: Select Issues', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Select Issues')
  })

  test('displays scored issues in table', async ({ page }) => {
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
    await expect(page.locator('text=fastify/fastify').first()).toBeVisible()
  })

  test('shows CVS score and tier badge', async ({ page }) => {
    // CVS 92 should appear as bold text
    await expect(page.locator('text=92').first()).toBeVisible()
    // go tier badge
    await expect(page.locator('.badge').filter({ hasText: /^go$/i }).first()).toBeVisible()
  })

  test('filter by CVS tier', async ({ page }) => {
    // Select "go" tier from the CVS Tier dropdown
    await page.locator('.filter-select').first().selectOption('go')
    // go-tier issue should remain
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
    // maybe-tier issue should be filtered out
    await expect(page.locator('text=Fix hydration warning')).not.toBeVisible()
  })

  test('select issues via checkbox and batch assign', async ({ page }) => {
    const checkbox = page.locator('input[type="checkbox"]').first()
    await checkbox.check()

    // "Assign Selected" button should show count
    await expect(page.getByRole('button', { name: /Assign Selected \(1\)/i })).toBeVisible()

    // Click Assign Selected — verify select-issue API is called
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/select-issue') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Assign Selected/i }).click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.origin_owner).toBeTruthy()
    expect(body.issue_number).toBeTruthy()
  })

  test('Select All / Select None buttons work', async ({ page }) => {
    await page.getByRole('button', { name: /^Select All$/i }).click()
    const checkboxes = page.locator('input[type="checkbox"]')
    const count = await checkboxes.count()
    expect(count).toBeGreaterThan(0)
    for (let i = 0; i < count; i++) {
      await expect(checkboxes.nth(i)).toBeChecked()
    }

    await page.getByRole('button', { name: /^Select None$/i }).click()
    for (let i = 0; i < count; i++) {
      await expect(checkboxes.nth(i)).not.toBeChecked()
    }
  })

  test('Dossier button opens dossier panel', async ({ page }) => {
    await page
      .getByRole('button', { name: /Dossier/i })
      .first()
      .click()
    // Dossier panel should appear with header and content
    await expect(page.locator('.dossier-panel')).toBeVisible({ timeout: 5000 })
    // Default tab is overview — verify overview content renders
    await expect(page.locator('text=Popular Node.js framework')).toBeVisible()
  })

  test('empty state when no scored issues', async ({ page }) => {
    await page.route('**/dispatch/api/oss/stage2-issues', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, issues: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Select Issues')
    await expect(page.locator('text=No scored issues')).toBeVisible()
  })
})

// ============ Stage 3: Fork & Assign ============

test.describe('OSS Pipeline - Stage 3: Fork & Assign', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Fork & Assign')
  })

  test('displays manual form and assignments table', async ({ page }) => {
    // Form inputs visible
    await expect(page.locator('input[placeholder="e.g. fastify"]').first()).toBeVisible()
    // Assignments table has data
    await expect(page.locator('text=fastify/fastify').first()).toBeVisible()
    await expect(page.locator('text=Fork #1')).toBeVisible()
  })

  test('fill form and submit, verify API body', async ({ page }) => {
    // Fill all form fields using label-based selectors
    const ownerInput = page.locator('input[placeholder="e.g. fastify"]').first()
    const repoInput = page.locator('input[placeholder="e.g. fastify"]').nth(1)
    const issueInput = page.locator('input[placeholder="e.g. 5432"]')
    const titleInput = page.locator('input[placeholder="Brief description of the issue"]')
    const urlInput = page.locator('input[placeholder*="https://github.com"]')

    await ownerInput.fill('lodash')
    await repoInput.fill('lodash')
    await issueInput.fill('999')
    await titleInput.fill('Fix sorting bug')
    await urlInput.fill('https://github.com/lodash/lodash/issues/999')

    // Click the form submit button (not the stage tab)
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/fork-and-assign') && req.method() === 'POST'
      ),
      page.locator('.oss-assign-form button[type="submit"]').click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.origin_owner).toBe('lodash')
    expect(body.repo).toBe('lodash')
    expect(body.issue_number).toBe(999)
    expect(body.issue_title).toBe('Fix sorting bug')
    expect(body.issue_url).toBe('https://github.com/lodash/lodash/issues/999')
  })

  test('empty assignments state', async ({ page }) => {
    await page.route('**/dispatch/api/oss/stage3-assigned', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, assignments: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Fork & Assign')
    await expect(page.locator('text=No active assignments')).toBeVisible()
  })
})

// ============ Stage 4: Review on Fork ============

test.describe('OSS Pipeline - Stage 4: Review on Fork', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Review on Fork')
  })

  test('displays ready and draft PR sections', async ({ page }) => {
    await expect(page.locator('text=Ready for Review')).toBeVisible()
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
    await expect(page.locator('text=In Progress')).toBeVisible()
  })

  test('View button opens PR modal with diff', async ({ page }) => {
    const [_request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/fork-pr-details') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^View$/i })
        .first()
        .click()
    ])

    // Modal should open — wait for loading to complete
    await expect(page.locator('.modal')).toBeVisible()
    await expect(page.locator('.modal__title')).toHaveText('Fix memory leak in request handler', {
      timeout: 5000
    })
  })

  test('Approve button triggers approve API call', async ({ page }) => {
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/approve-fork-pr') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^Approve$/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.repo).toBe('fastify')
    expect(body.pr_number).toBe(1)
  })

  test('Merge button triggers merge API call', async ({ page }) => {
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/merge-fork-pr') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^Merge$/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.repo).toBe('fastify')
    expect(body.pr_number).toBe(1)
    expect(body.origin_slug).toBe('fastify/fastify')
  })

  test('empty state when no fork PRs', async ({ page }) => {
    await page.route('**/dispatch/api/oss/stage4-fork-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, prs: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Review on Fork')
    await expect(page.locator('text=No fork PRs')).toBeVisible()
  })
})

// ============ Stage 5: Submit Upstream ============

test.describe('OSS Pipeline - Stage 5: Submit Upstream', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Submit Upstream')
  })

  test('displays ready-to-submit table', async ({ page }) => {
    await expect(page.locator('text=Ready to Submit')).toBeVisible()
    await expect(page.locator('text=fastify/fastify').first()).toBeVisible()
    await expect(page.locator('text=fix/memory-leak')).toBeVisible()
  })

  test('Submit button opens inline editor', async ({ page }) => {
    // Click the Submit button in the actions column
    await page
      .locator('.data-table .btn--primary')
      .filter({ hasText: /^Submit$/ })
      .first()
      .click()
    // Editor heading should appear
    await expect(page.locator('text=Edit PR before submitting')).toBeVisible()
    // Title input should be pre-filled
    const titleInput = page.locator('.oss-submit-editor input')
    await expect(titleInput).toHaveValue('Fix memory leak in request handler')
    // Body textarea should exist
    await expect(page.locator('.oss-submit-editor textarea')).toBeVisible()
  })

  test('Confirm Submit triggers submit-to-origin API', async ({ page }) => {
    // Open editor
    await page
      .locator('.data-table .btn--primary')
      .filter({ hasText: /^Submit$/ })
      .first()
      .click()
    await expect(page.locator('text=Edit PR before submitting')).toBeVisible()

    // Modify title
    const titleInput = page.locator('.oss-submit-editor input')
    await titleInput.clear()
    await titleInput.fill('fix: memory leak in request handler')

    // Click Confirm Submit
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/submit-to-origin') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Confirm Submit/i }).click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.origin_slug).toBe('fastify/fastify')
    expect(body.repo).toBe('fastify')
    expect(body.branch).toBe('fix/memory-leak')
    expect(body.title).toBe('fix: memory leak in request handler')
    expect(body.base_branch).toBe('main')
  })

  test('Cancel button closes inline editor', async ({ page }) => {
    await page
      .locator('.data-table .btn--primary')
      .filter({ hasText: /^Submit$/ })
      .first()
      .click()
    await expect(page.locator('text=Edit PR before submitting')).toBeVisible()
    await page.getByRole('button', { name: /Cancel/i }).click()
    await expect(page.locator('text=Edit PR before submitting')).not.toBeVisible()
  })

  test('displays submitted PRs tracking section', async ({ page }) => {
    // Auto-polled on mount
    await expect(page.locator('text=Submitted PRs').first()).toBeVisible()
    await expect(page.locator('text=#9876')).toBeVisible()
  })

  test('Refresh Status button triggers poll API', async ({ page }) => {
    // Wait for initial auto-poll to finish
    await expect(page.locator('text=#9876')).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/dispatch/api/oss/poll-submitted-prs') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Refresh Status/i }).click()
    ])

    expect(request).toBeTruthy()
  })

  test('empty state when nothing to submit or track', async ({ page }) => {
    await page.route('**/dispatch/api/oss/stage5-submit', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, ready: [], owner: mockOwner })
      })
    })
    await page.route('**/dispatch/api/oss/poll-submitted-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, submitted: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Submit Upstream')
    await expect(page.locator('text=No submissions yet')).toBeVisible()
  })
})

// ============ Stage Navigation ============

test.describe('OSS Pipeline - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('can navigate to OSS view and see all 5 stage tabs', async ({ page }) => {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()

    const stageLabels = [
      'Target Repos',
      'Select Issues',
      'Fork & Assign',
      'Review on Fork',
      'Submit Upstream'
    ]
    for (const label of stageLabels) {
      await expect(page.locator('.stage-tab__label').filter({ hasText: label })).toBeVisible()
    }
  })

  test('default tab is Fork & Assign (Stage 3)', async ({ page }) => {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()
    const activeTab = page.locator('.stage-tab--active')
    await expect(activeTab).toBeVisible()
    await expect(activeTab.locator('.stage-tab__label')).toHaveText('Fork & Assign')
  })

  test('stage tabs show item counts', async ({ page }) => {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()
    // Target Repos tab should show count (2 targets)
    const targetTab = page.locator('.stage-tab').filter({ hasText: 'Target Repos' })
    const countSpan = targetTab.locator('.stage-tab__count')
    await expect(countSpan).toHaveText('2')
  })

  test('can navigate between all 5 OSS stages', async ({ page }) => {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()

    const stages = [
      'Target Repos',
      'Select Issues',
      'Fork & Assign',
      'Review on Fork',
      'Submit Upstream'
    ]
    for (const stage of stages) {
      await page.locator('.stage-tab').filter({ hasText: stage }).click()
      await page.waitForTimeout(200)
    }
    // Should still be on OSS view
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' })).toBeVisible()
  })

  test('Refresh All button exists and works', async ({ page }) => {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()
    const refreshBtn = page.getByRole('button', { name: /Refresh All/i })
    await expect(refreshBtn).toBeVisible()
    await refreshBtn.click()
    // Should not crash — title still visible
    await expect(page.locator('text=VibeDispatch')).toBeVisible()
  })
})
