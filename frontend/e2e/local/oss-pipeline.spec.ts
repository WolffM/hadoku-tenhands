/**
 * E2E Tests for the OSS Contribution Pipeline (4-tab redesign)
 *
 * Tests navigation, data display, button interactions, filtering,
 * and empty states across all OSS pipeline tabs:
 *   Tab 1: Repo Health
 *   Tab 2: Fork & Assign
 *   Tab 3: Pipeline Runs
 *   Tab 4: Review
 */

import { test, expect, type Page } from '../fixtures/base'
import {
  mockAllAPIs,
  mockOwner,
  mockOSSTargets,
  mockOSSScoredIssues,
  mockPipelineStatuses,
  mockOSSSubmittedPRs
} from '../fixtures/api-mocks'

/** Navigate to a specific OSS pipeline stage tab */
async function navigateToOSSStage(page: Page, stageLabel: string): Promise<void> {
  await expect(page.locator('text=TenHands')).toBeVisible()

  const ossCard = page
    .locator('.pipeline-select-card')
    .filter({ hasText: 'OSS Contribution Pipeline' })
  if (await ossCard.isVisible()) {
    await ossCard.click()
  } else {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()
  }
  // Default tab is Pipeline Runs
  await expect(page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })).toBeVisible()
  if (stageLabel !== 'Pipeline Runs') {
    await page.locator('.stage-tab').filter({ hasText: stageLabel }).click()
  }
}

// ============ Tab 1: Repo Health ============

test.describe('OSS Pipeline - Tab 1: Repo Health', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Repo Health')
  })

  test('renders repo health cards with slugs', async ({ page }) => {
    await expect(page.locator('text=acme-corp-widget-api').first()).toBeVisible()
    await expect(page.locator('text=vercel-next.js').first()).toBeVisible()
  })

  test('shows health badge with overall viability score', async ({ page }) => {
    // acme-corp-widget-api has overallViability = 82
    await expect(page.locator('.badge').filter({ hasText: '82' })).toBeVisible()
    // vercel-next.js has overallViability = 58
    await expect(page.locator('.badge').filter({ hasText: '58' })).toBeVisible()
  })

  test('shows sub-scores (maintainer, merge access, availability)', async ({ page }) => {
    await expect(page.locator('text=85%').first()).toBeVisible()
    await expect(page.locator('text=72%').first()).toBeVisible()
    await expect(page.locator('text=90%').first()).toBeVisible()
  })

  test('dossier sections are expandable/collapsible', async ({ page }) => {
    // Find the Overview toggle within the first repo card
    const overviewToggle = page
      .locator('.repo-health-card__section-toggle')
      .filter({ hasText: 'Overview' })
      .first()
    await expect(overviewToggle).toBeVisible()

    // Click to expand
    await overviewToggle.click()
    await expect(page.locator('text=Popular Node.js framework').first()).toBeVisible()

    // Click again to collapse
    await overviewToggle.click()
    await expect(page.locator('.repo-health-card__section-content').first()).not.toBeVisible()
  })

  test('Re-scrape button triggers refresh-target API call', async ({ page }) => {
    await expect(page.locator('text=acme-corp-widget-api').first()).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/refresh-target') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /Re-scrape/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.slug).toBeTruthy()
  })

  test('Re-compute button triggers compute-target API call', async ({ page }) => {
    await expect(page.locator('text=acme-corp-widget-api').first()).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/compute-target') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /Re-compute/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.slug).toBeTruthy()
  })

  test('empty state when no targets', async ({ page }) => {
    await page.route('**/tenhands/api/oss/stage1-targets', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, targets: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Repo Health')
    await expect(page.locator('text=No target repos')).toBeVisible()
  })
})

// ============ Tab 2: Fork & Assign ============

test.describe('OSS Pipeline - Tab 2: Fork & Assign', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Fork & Assign')
  })

  test('displays scored issues in table', async ({ page }) => {
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
    await expect(page.locator('text=acme-corp/widget-api').first()).toBeVisible()
  })

  test('shows CVS score and tier badge', async ({ page }) => {
    await expect(page.locator('text=92').first()).toBeVisible()
    await expect(page.locator('.badge').filter({ hasText: /^go$/i }).first()).toBeVisible()
  })

  test('global repo filter hides issues from excluded repos', async ({ page }) => {
    // Initially all 3 issues visible
    await expect(page.locator('text=All Issues (3)')).toBeVisible()

    // Open the global filter popover
    const trigger = page.locator('.repo-filter-trigger')
    await expect(trigger).toBeVisible()
    await trigger.click()
    await expect(page.locator('.repo-filter-popover__panel')).toBeVisible()

    // Uncheck vercel/next.js
    const nextjsCheckbox = page
      .locator('.repo-filter-popover__item')
      .filter({ hasText: 'vercel/next.js' })
      .locator('input')
    await nextjsCheckbox.uncheck()

    // Close popover by clicking trigger again
    await trigger.click()

    // Should only show 2 widget-api issues
    await expect(page.locator('text=All Issues (2)')).toBeVisible()
    await expect(page.locator('text=Fix hydration warning')).not.toBeVisible()
  })

  test('recommended section shows top issues', async ({ page }) => {
    // Recommended shows go + likely tier issues (CVS 92 and 65)
    await expect(page.locator('text=Recommended').first()).toBeVisible()
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
  })

  test('Assign Selected in Recommended section triggers fork-and-assign API', async ({ page }) => {
    // Select all recommended issues first
    await page.getByRole('button', { name: /^Select All$/i }).click()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/fork-and-assign') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Assign Selected/i }).click()
    ])

    expect(request).toBeTruthy()
  })

  test('filter by CVS tier', async ({ page }) => {
    const tierSelect = page.locator('.filter-select').first()
    await tierSelect.selectOption('go')
    // go-tier issue (CVS 92) should remain
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
    // maybe-tier issue should be filtered out
    await expect(page.locator('text=Fix hydration warning')).not.toBeVisible()
  })

  test('select issues via checkbox and batch assign', async ({ page }) => {
    // Checkboxes are in the Recommended section table
    const recommendedSection = page.locator('.stage-section').filter({ hasText: 'Recommended' })
    const checkbox = recommendedSection.locator('.data-table input[type="checkbox"]').first()
    await checkbox.check()

    await expect(page.getByRole('button', { name: /Assign Selected \(1\)/i })).toBeVisible()

    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/select-issue') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Assign Selected/i }).click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.origin_owner).toBeTruthy()
    expect(body.issue_number).toBeTruthy()
  })

  test('Select All / Select None buttons work', async ({ page }) => {
    // Select All/None are in the Recommended section
    const recommendedSection = page.locator('.stage-section').filter({ hasText: 'Recommended' })
    const checkboxes = recommendedSection.locator('.data-table input[type="checkbox"]')

    await page.getByRole('button', { name: /^Select All$/i }).click()
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
    await expect(page.locator('.dossier-panel')).toBeVisible({ timeout: 5000 })
  })

  test('empty state when no scored issues', async ({ page }) => {
    await page.route('**/tenhands/api/oss/stage2-issues', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, issues: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Fork & Assign')
    await expect(page.locator('text=No scored issues')).toBeVisible()
  })
})

// ============ Tab 3: Pipeline Runs ============

test.describe('OSS Pipeline - Tab 3: Pipeline Runs', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Pipeline Runs')
  })

  test('renders summary metric cards', async ({ page }) => {
    // Total = 2 assignments, Completed = 1 (retrospective_complete), In Progress = 1
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Total' })).toBeVisible()
    await expect(page.locator('.metric-card__value').filter({ hasText: '2' }).first()).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Completed' })).toBeVisible()
    await expect(
      page.locator('.metric-card__label').filter({ hasText: 'In Progress' })
    ).toBeVisible()
  })

  test('renders assignment rows with origin repo and issue number', async ({ page }) => {
    await expect(page.locator('text=acme-corp/widget-api').first()).toBeVisible()
    await expect(page.locator('text=#1234').first()).toBeVisible()
    await expect(page.locator('text=vercel/next.js').first()).toBeVisible()
    await expect(page.locator('text=#9999').first()).toBeVisible()
  })

  test('renders progress bars with segments', async ({ page }) => {
    const progressBars = page.locator('.pipeline-progress')
    await expect(progressBars).toHaveCount(2)
    // The completed assignment should have all segments filled
    const filledSegments = page.locator('.pipeline-progress__seg--filled')
    const count = await filledSegments.count()
    expect(count).toBeGreaterThan(0)
  })

  test('status badges render correctly', async ({ page }) => {
    // retrospective_complete => badge--success
    await expect(
      page.locator('.badge--success').filter({ hasText: /retrospective complete/i })
    ).toBeVisible()
    // static_analysis_running => badge--primary (contains "running")
    await expect(
      page.locator('.badge--primary').filter({ hasText: /static analysis running/i })
    ).toBeVisible()
  })

  test('Report button opens modal with iframe that loads without errors', async ({ page }) => {
    // Collect errors from the iframe
    const iframeErrors: string[] = []

    await page
      .getByRole('button', { name: /^Report$/i })
      .first()
      .click()

    // Report modal should appear
    await expect(page.locator('.report-modal')).toBeVisible()
    await expect(page.locator('.report-modal__iframe')).toBeVisible()

    // Iframe src should point to the issue report endpoint
    const iframe = page.locator('.report-modal__iframe')
    const src = await iframe.getAttribute('src')
    expect(src).toContain('/tenhands/api/oss/issue-report/')

    // Wait for the iframe frame to load and verify no JS errors
    const iframeFrame = page.frameLocator('.report-modal__iframe')

    // Listen for errors on the iframe's frame
    const frames = page.frames()
    const reportFrame = frames.find(f => f.url().includes('/tenhands/api/oss/issue-report/'))
    if (reportFrame) {
      ;(
        reportFrame as unknown as {
          on: (event: string, cb: (msg: { type: () => string; text: () => string }) => void) => void
        }
      ).on('console', (msg: { type: () => string; text: () => string }) => {
        if (msg.type() === 'error') iframeErrors.push(msg.text())
      })
    }

    // Verify the report content rendered (not just the header)
    await expect(iframeFrame.locator('h1')).toContainText('Pipeline Report')
    await expect(iframeFrame.locator('#headerSub')).not.toBeEmpty()
    // The mock report should show "Report loaded successfully"
    await expect(iframeFrame.locator('#app')).not.toBeEmpty()

    // Check no JS errors occurred in the iframe
    expect(iframeErrors).toEqual([])
  })

  test('Report modal can be closed', async ({ page }) => {
    await page
      .getByRole('button', { name: /^Report$/i })
      .first()
      .click()
    await expect(page.locator('.report-modal')).toBeVisible()

    // Close the modal
    await page.locator('.report-modal__header').getByRole('button', { name: /Close/i }).click()
    await expect(page.locator('.report-modal')).not.toBeVisible()
  })

  test('Advance button triggers advance-pipeline API', async ({ page }) => {
    // Advance button should only show for non-complete assignments
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/advance-pipeline') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^Advance$/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.repo).toBeTruthy()
    expect(body.fork_issue_number).toBeTruthy()
  })

  test('Signoff button triggers signoff API for completed assignment', async ({ page }) => {
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/signoff') && req.method() === 'POST'
      ),
      page
        .getByRole('button', { name: /^Signoff$/i })
        .first()
        .click()
    ])

    const body = request.postDataJSON() as Record<string, unknown>
    expect(body.repo).toBe('widget-api')
    expect(body.pr_number).toBe(10)
    expect(body.origin_slug).toBe('acme-corp/widget-api')
  })

  test('Signoff button shows loading state', async ({ page }) => {
    // Delay the signoff response
    await page.route('**/tenhands/api/oss/signoff', async route => {
      await new Promise(resolve => setTimeout(resolve, 2000))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          pr_url: 'https://github.com/acme-corp/widget-api/pull/5555',
          owner: mockOwner
        })
      })
    })

    const signoffBtn = page.getByRole('button', { name: /^Signoff$/i }).first()
    await signoffBtn.click()
    await expect(page.locator('text=Signing off...')).toBeVisible()
  })

  test('empty state when no assignments', async ({ page }) => {
    await page.route('**/tenhands/api/oss/pipeline-status', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, statuses: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Pipeline Runs')
    await expect(page.locator('text=No pipeline runs')).toBeVisible()
  })
})

// ============ Tab 4: Review ============

test.describe('OSS Pipeline - Tab 4: Review', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Review')
  })

  test('renders summary count cards', async ({ page }) => {
    // 2 total PRs, 1 open, 1 merged, 0 closed
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Total' })).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Open' })).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Merged' })).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Closed' })).toBeVisible()
  })

  test('renders submitted PR table with all columns', async ({ page }) => {
    // Check table headers
    await expect(page.locator('th').filter({ hasText: 'Origin Repo' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'PR' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Title' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Status' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Comments' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Labels' })).toBeVisible()
  })

  test('shows PR data correctly', async ({ page }) => {
    await expect(page.locator('text=acme-corp/widget-api').first()).toBeVisible()
    await expect(page.locator('text=#9876')).toBeVisible()
    await expect(page.locator('text=Fix memory leak in request handler').first()).toBeVisible()
  })

  test('status badges render correctly for different states', async ({ page }) => {
    // Open PR => badge--primary "Open"
    await expect(page.locator('.badge--primary').filter({ hasText: 'Open' })).toBeVisible()
    // Merged PR => badge--success "Merged"
    await expect(page.locator('.badge--success').filter({ hasText: 'Merged' })).toBeVisible()
  })

  test('comment count is displayed', async ({ page }) => {
    // widget-api PR has comment_count: 3
    await expect(page.locator('td').filter({ hasText: '3' }).first()).toBeVisible()
  })

  test('labels are displayed', async ({ page }) => {
    await expect(page.locator('text=bug, good first issue')).toBeVisible()
  })

  test('Refresh Status button triggers poll API', async ({ page }) => {
    const [request] = await Promise.all([
      page.waitForRequest(
        req => req.url().includes('/tenhands/api/oss/poll-submitted-prs') && req.method() === 'POST'
      ),
      page.getByRole('button', { name: /Refresh Status/i }).click()
    ])

    expect(request).toBeTruthy()
  })

  test('empty state when no submitted PRs', async ({ page }) => {
    await page.route('**/tenhands/api/oss/poll-submitted-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, submitted: [], owner: mockOwner })
      })
    })
    await page.goto('/?key=test-key')
    await navigateToOSSStage(page, 'Review')
    await expect(page.locator('text=No submitted PRs')).toBeVisible()
  })
})

// ============ Tab Navigation ============

test.describe('OSS Pipeline - Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
  })

  test('can navigate to OSS view and see all 4 stage tabs', async ({ page }) => {
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()

    const stageLabels = ['Repo Health', 'Fork & Assign', 'Pipeline Runs', 'Review']
    for (const label of stageLabels) {
      await expect(page.locator('.stage-tab__label').filter({ hasText: label })).toBeVisible()
    }
  })

  test('default tab is Pipeline Runs', async ({ page }) => {
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    const activeTab = page.locator('.stage-tab--active')
    await expect(activeTab).toBeVisible()
    await expect(activeTab.locator('.stage-tab__label')).toHaveText('Pipeline Runs')
  })

  test('stage tabs show item counts', async ({ page }) => {
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    // Repo Health tab should show count (2 targets)
    const healthTab = page.locator('.stage-tab').filter({ hasText: 'Repo Health' })
    const countSpan = healthTab.locator('.stage-tab__count')
    await expect(countSpan).toHaveText('2')
  })

  test('can navigate between all 4 OSS tabs', async ({ page }) => {
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()

    const tabs = ['Repo Health', 'Fork & Assign', 'Pipeline Runs', 'Review']
    for (const tab of tabs) {
      await page.locator('.stage-tab').filter({ hasText: tab }).click()
      await page.waitForTimeout(200)
    }
    // Should still be on OSS view
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' })).toBeVisible()
  })

  test('Refresh All button exists and works', async ({ page }) => {
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    const refreshBtn = page.getByRole('button', { name: /Refresh All/i })
    await expect(refreshBtn).toBeVisible()
    await refreshBtn.click()
    // Should not crash
    await expect(page.locator('text=TenHands')).toBeVisible()
  })
})

// ============ Global Repo Filter ============

test.describe('OSS Pipeline - Global Repo Filter', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await page.goto('/?key=test-key')
    // Navigate to OSS view (default tab is Pipeline Runs)
    const ossCard = page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
    await ossCard.click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible()
  })

  test('filter popover opens and closes', async ({ page }) => {
    const trigger = page.locator('.repo-filter-trigger')
    await expect(trigger).toBeVisible()

    await trigger.click()
    await expect(page.locator('.repo-filter-popover__panel')).toBeVisible()

    // Click trigger again to close
    await trigger.click()
    await expect(page.locator('.repo-filter-popover__panel')).not.toBeVisible()
  })

  test('filter trigger shows count', async ({ page }) => {
    const trigger = page.locator('.repo-filter-trigger')
    // Should show count like "Repos (X of Y)"
    await expect(trigger).toContainText('Repos')
    await expect(trigger).toContainText('of')
  })

  test('search filters the repo list', async ({ page }) => {
    const trigger = page.locator('.repo-filter-trigger')
    await trigger.click()

    const searchInput = page.locator('.repo-filter-popover__search input')
    await searchInput.fill('widget-api')

    // Only widget-api repos should show
    const items = page.locator('.repo-filter-popover__item')
    const count = await items.count()
    expect(count).toBeGreaterThan(0)
    for (let i = 0; i < count; i++) {
      await expect(items.nth(i)).toContainText('widget-api')
    }
  })

  test('All/None buttons work', async ({ page }) => {
    const trigger = page.locator('.repo-filter-trigger')
    await trigger.click()

    // Click None
    await page
      .locator('.repo-filter-popover__actions')
      .getByRole('button', { name: 'None' })
      .click()

    // All checkboxes should be unchecked
    const checkboxes = page.locator('.repo-filter-popover__item input[type="checkbox"]')
    const count = await checkboxes.count()
    for (let i = 0; i < count; i++) {
      await expect(checkboxes.nth(i)).not.toBeChecked()
    }

    // Click All
    await page.locator('.repo-filter-popover__actions').getByRole('button', { name: 'All' }).click()

    // All checkboxes should be checked
    for (let i = 0; i < count; i++) {
      await expect(checkboxes.nth(i)).toBeChecked()
    }
  })

  test('filter applies across tabs', async ({ page }) => {
    // Open filter and exclude vercel/next.js
    const trigger = page.locator('.repo-filter-trigger')
    await trigger.click()

    const nextjsCheckbox = page
      .locator('.repo-filter-popover__item')
      .filter({ hasText: 'vercel/next.js' })
      .locator('input')
    await nextjsCheckbox.uncheck()
    await trigger.click() // close

    // Tab 3 (Pipeline Runs) — vercel/next.js assignment should be hidden
    await expect(
      page.locator('.data-table td').filter({ hasText: 'vercel/next.js' })
    ).not.toBeVisible()
    await expect(
      page.locator('.data-table td').filter({ hasText: 'acme-corp/widget-api' }).first()
    ).toBeVisible()

    // Tab 2 (Fork & Assign) — vercel issues should be hidden
    await page.locator('.stage-tab').filter({ hasText: 'Fork & Assign' }).click()
    await expect(page.locator('text=Fix hydration warning')).not.toBeVisible()
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()
  })
})

// ============ Full Pipeline Walkthrough ============

test.describe('OSS Pipeline - Full Walkthrough', () => {
  test('walks through all 4 tabs with stateful mocks', async ({ page }) => {
    // Set up base mocks
    await page.route('**/tenhands/api/owner', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: mockOwner })
      })
    })

    // OSS stage mocks
    await page.route('**/tenhands/api/oss/stage1-targets', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, targets: mockOSSTargets, owner: mockOwner })
      })
    })

    await page.route('**/tenhands/api/oss/stage2-issues', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, issues: mockOSSScoredIssues, owner: mockOwner })
      })
    })

    await page.route('**/tenhands/api/oss/pipeline-status', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, statuses: mockPipelineStatuses, owner: mockOwner })
      })
    })

    await page.route('**/tenhands/api/oss/retrospective-logs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, logs: [], owner: mockOwner })
      })
    })

    await page.route('**/tenhands/api/oss/poll-submitted-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, submitted: mockOSSSubmittedPRs, owner: mockOwner })
      })
    })

    await page.route('**/tenhands/api/oss/issue-report/**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: `<!DOCTYPE html><html><head><title>Pipeline Report</title>
<style>body{background:#0d1117;color:#e6edf3;font-family:sans-serif;display:flex;justify-content:center;}
.shell{width:90%;}.header h1{font-size:1.3em;}.empty-detail{padding:48px;text-align:center;color:#8b949e;}</style></head>
<body><div class="shell"><div class="header"><h1>Pipeline Report</h1><div class="sub" id="headerSub"></div></div>
<div id="runTabs"></div><div id="app"></div></div>
<script>
const DATA = {"repo":"test","health":{},"runs":[]};
let activeRun = Math.max(0, DATA.runs.length - 1);
function renderContent() {
  const run = DATA.runs[activeRun];
  if (!run) { document.getElementById('headerSub').textContent='No data'; document.getElementById('app').innerHTML='<div class="empty-detail">No retrospective logs found.</div>'; return; }
  document.getElementById('app').innerHTML='Loaded';
}
renderContent();
</script></body></html>`
      })
    })

    await page.route('**/tenhands/api/oss/dossier/**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          dossier: {
            slug: 'acme-corp-widget-api',
            generatedAt: new Date().toISOString(),
            sections: {
              overview: 'Popular framework',
              contributionRules: 'Follow the style guide.'
            }
          },
          owner: mockOwner
        })
      })
    })

    // Action mocks with tracking
    let refreshTargetCalled = false
    await page.route('**/tenhands/api/oss/refresh-target', async route => {
      refreshTargetCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: mockOwner })
      })
    })

    let computeTargetCalled = false
    await page.route('**/tenhands/api/oss/compute-target', async route => {
      computeTargetCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, message: 'Computed', owner: mockOwner })
      })
    })

    let selectIssueCalled = false
    await page.route('**/tenhands/api/oss/select-issue', async route => {
      selectIssueCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: mockOwner })
      })
    })

    let _forkAndAssignCalled = false
    await page.route('**/tenhands/api/oss/fork-and-assign', async route => {
      _forkAndAssignCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          fork_issue_url: 'https://github.com/test-user/widget-api/issues/3',
          fork_issue_number: 3,
          owner: mockOwner
        })
      })
    })

    let signoffCalled = false
    await page.route('**/tenhands/api/oss/signoff', async route => {
      signoffCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          pr_url: 'https://github.com/acme-corp/widget-api/pull/5555',
          owner: mockOwner
        })
      })
    })

    let advanceCalled = false
    await page.route('**/tenhands/api/oss/advance-pipeline', async route => {
      advanceCalled = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: mockOwner })
      })
    })

    // Also mock vibecheck endpoints (loaded in background)
    await page.route('**/tenhands/api/stage1-repos', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: mockOwner, repos: [] })
      })
    })

    await page.route('**/tenhands/api/stage4-prs', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, owner: mockOwner, prs: [] })
      })
    })

    await page.route('**/tenhands/api/stage3-issues', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          owner: mockOwner,
          issues: [],
          labels: [],
          repos_with_copilot_prs: []
        })
      })
    })

    // -------- Start --------
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible()

    // -------- Tab 1: Repo Health --------
    await page.locator('.stage-tab').filter({ hasText: 'Repo Health' }).click()
    await expect(page.locator('text=acme-corp-widget-api').first()).toBeVisible()

    // Re-scrape
    await page
      .getByRole('button', { name: /Re-scrape/i })
      .first()
      .click()
    expect(refreshTargetCalled).toBe(true)

    // Re-compute
    await page
      .getByRole('button', { name: /Re-compute/i })
      .first()
      .click()
    expect(computeTargetCalled).toBe(true)

    // -------- Tab 2: Fork & Assign --------
    await page.locator('.stage-tab').filter({ hasText: 'Fork & Assign' }).click()
    await expect(page.locator('text=Fix memory leak').first()).toBeVisible()

    // Select and assign
    const checkbox = page.locator('.data-table input[type="checkbox"]').first()
    await checkbox.check()
    await page.getByRole('button', { name: /Assign Selected/i }).click()
    expect(selectIssueCalled).toBe(true)

    // -------- Tab 3: Pipeline Runs --------
    await page.locator('.stage-tab').filter({ hasText: 'Pipeline Runs' }).click()
    await expect(page.locator('text=acme-corp/widget-api').first()).toBeVisible()

    // Open report and verify iframe content loads
    await page
      .getByRole('button', { name: /^Report$/i })
      .first()
      .click()
    await expect(page.locator('.report-modal')).toBeVisible()
    const walkIframe = page.frameLocator('.report-modal__iframe')
    await expect(walkIframe.locator('h1')).toContainText('Pipeline Report')
    await page.locator('.report-modal__header').getByRole('button', { name: /Close/i }).click()
    await expect(page.locator('.report-modal')).not.toBeVisible()

    // Advance non-complete assignment
    await page
      .getByRole('button', { name: /^Advance$/i })
      .first()
      .click()
    expect(advanceCalled).toBe(true)

    // Signoff completed assignment
    await page
      .getByRole('button', { name: /^Signoff$/i })
      .first()
      .click()
    expect(signoffCalled).toBe(true)

    // -------- Tab 4: Review --------
    await page.locator('.stage-tab').filter({ hasText: 'Review' }).click()
    await expect(page.locator('text=#9876')).toBeVisible()
    await expect(page.locator('.badge--primary').filter({ hasText: 'Open' })).toBeVisible()
    await expect(page.locator('.badge--success').filter({ hasText: 'Merged' })).toBeVisible()

    // -------- Navigate Home --------
    await page.getByRole('button', { name: /^Home$/i }).click()
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
  })
})
