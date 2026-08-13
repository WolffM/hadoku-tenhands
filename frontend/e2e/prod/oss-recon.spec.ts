/**
 * Production E2E Tests — OSS Recon Pipeline
 *
 * Hits the REAL Flask backend (port 5001) via Vite dev server (port 5184).
 * No route interception — all API calls go to the real aggregator + gh CLI.
 *
 * Requirements:
 *   - Flask backend running on port 5001 with .env loaded
 *   - gh CLI authenticated (gh auth status)
 *   - Aggregator at https://hadoku.me/oss/api (may be down — tests handle gracefully)
 *
 * Run: cd frontend && pnpm test:prod
 */

import { test, expect } from '../fixtures/prod-base'
import type { Page } from '@playwright/test'

// Real backend is slower — use generous timeouts
const LOAD_TIMEOUT = 30_000
const ACTION_TIMEOUT = 15_000

// ---------- Helpers ----------

/**
 * Navigate from landing page to a specific OSS pipeline tab.
 * Waits for initial data load to finish before asserting tab content.
 */
async function navigateToOSSTab(page: Page, tabLabel: string): Promise<void> {
  await page.goto('/')
  await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })

  // Click the OSS pipeline card or nav tab
  const ossCard = page
    .locator('.pipeline-select-card')
    .filter({ hasText: 'OSS Contribution Pipeline' })
  if (await ossCard.isVisible({ timeout: 5000 }).catch(() => false)) {
    await ossCard.click()
  } else {
    await page.locator('.nav-tabs__tab').filter({ hasText: 'OSS Contrib' }).click()
  }

  // Wait for stage tabs to appear (default tab is Pipeline Runs)
  await expect(page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })).toBeVisible({
    timeout: LOAD_TIMEOUT
  })

  // Wait for the refresh button to appear (either state — loading may be in progress)
  const refreshAllBtn = page.getByRole('button', { name: 'Refresh All' })
  const refreshingBtn = page.getByRole('button', { name: 'Refreshing…' })
  await expect(refreshAllBtn.or(refreshingBtn)).toBeVisible({ timeout: LOAD_TIMEOUT })

  // If still refreshing, wait for it to finish (can take 45s+ with many repos)
  if (await refreshingBtn.isVisible().catch(() => false)) {
    await expect(refreshAllBtn).toBeVisible({ timeout: 50_000 })
  }

  // Navigate to the requested tab
  if (tabLabel !== 'Pipeline Runs') {
    await page.locator('.stage-tab').filter({ hasText: tabLabel }).click()
    // Wait for the tab to become active before asserting its content
    await expect(page.locator('.stage-tab--active').filter({ hasText: tabLabel })).toBeVisible({
      timeout: 5000
    })
  }
}

/**
 * Assert that data loaded, empty state shows, or loading state is visible.
 * All three are valid outcomes when hitting a real backend.
 * Returns 'data' | 'empty' | 'loading'.
 */
async function waitForPanelState(
  page: Page,
  dataSelector: string,
  emptyText: string,
  loadingText: string
): Promise<'data' | 'empty' | 'loading'> {
  const dataLocator = page.locator(dataSelector).first()
  const emptyLocator = page.locator(`text=${emptyText}`)
  const loadingLocator = page.locator(`text=${loadingText}`)

  // Wait for one of the three states
  await expect(dataLocator.or(emptyLocator).or(loadingLocator)).toBeVisible({
    timeout: LOAD_TIMEOUT
  })

  if (await dataLocator.isVisible().catch(() => false)) return 'data'
  if (await emptyLocator.isVisible().catch(() => false)) return 'empty'
  return 'loading'
}

// ============ Backend Health Gate ============

test.describe('Prod: Backend Health', () => {
  test.describe.configure({ mode: 'serial' })

  test('backend healthcheck returns OK', async ({ request }) => {
    const response = await request.get('/tenhands/api/healthcheck')
    expect(response.ok()).toBeTruthy()
    const data = (await response.json()) as { success: boolean; owner: string }
    expect(data.success).toBe(true)
    expect(data.owner).toBeTruthy()
  })

  test('gh CLI is authenticated', async ({ request }) => {
    const response = await request.get('/tenhands/api/oss/debug/gh-health')
    expect(response.ok()).toBeTruthy()
    const data = (await response.json()) as {
      success: boolean
      authenticated: boolean
      api_working: boolean
    }
    expect(data.success).toBe(true)
    expect(data.authenticated).toBe(true)
    expect(data.api_working).toBe(true)
  })

  test('aggregator connectivity is known', async ({ request }) => {
    const response = await request.get('/tenhands/api/oss/debug/aggregator-health')
    expect(response.ok()).toBeTruthy()
    const data = (await response.json()) as {
      success: boolean
      configured: boolean
      reachable: boolean
    }
    expect(data.success).toBe(true)
    expect(typeof data.configured).toBe('boolean')
    expect(typeof data.reachable).toBe('boolean')
  })
})

// ============ Navigation ============

test.describe('Prod: OSS Navigation', () => {
  test('landing page loads with pipeline selection', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await expect(
      page.locator('.pipeline-select-card').filter({ hasText: 'OSS Contribution Pipeline' })
    ).toBeVisible()
  })

  test('can navigate to OSS pipeline and see all 4 tabs', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })

    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()

    const expectedTabs = ['Repo Health', 'Fork & Assign', 'Pipeline Runs', 'Review']
    for (const label of expectedTabs) {
      await expect(page.locator('.stage-tab__label').filter({ hasText: label })).toBeVisible({
        timeout: LOAD_TIMEOUT
      })
    }
  })

  test('default tab is Pipeline Runs', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')
    const activeTab = page.locator('.stage-tab--active')
    await expect(activeTab.locator('.stage-tab__label')).toHaveText('Pipeline Runs')
  })

  test('can navigate between all 4 tabs without errors', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const tabs = ['Fork & Assign', 'Pipeline Runs', 'Review', 'Repo Health']
    for (const tab of tabs) {
      await page.locator('.stage-tab').filter({ hasText: tab }).click()
      await expect(page.locator('.stage-tab--active').filter({ hasText: tab })).toBeVisible({
        timeout: 5000
      })
    }
  })

  test('Refresh All button works', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    // After navigateToOSSTab, button should say "Refresh All" (load completed)
    const refreshBtn = page.getByRole('button', { name: 'Refresh All' })
    await expect(refreshBtn).toBeVisible()
    await refreshBtn.click()

    // Should show "Refreshing…" then go back to "Refresh All"
    await expect(page.getByRole('button', { name: 'Refreshing…' })).toBeVisible({
      timeout: 5000
    })
    await expect(page.getByRole('button', { name: 'Refresh All' })).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
  })

  test('Home button returns to pipeline selection', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')
    await page.getByRole('button', { name: /^Home$/i }).click()
    await expect(page.locator('text=Select a Pipeline')).toBeVisible({ timeout: LOAD_TIMEOUT })
  })

  test('Vibecheck Pipeline card navigates to vibecheck view', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })

    const vibecheckCard = page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'Vibecheck Pipeline' })
    await expect(vibecheckCard).toBeVisible()
    await vibecheckCard.click()

    // Should leave the select view (no longer showing "Select a Pipeline")
    await expect(page.locator('text=Select a Pipeline')).not.toBeVisible({ timeout: 5000 })
    // Should show navigation with Home button
    await expect(page.getByRole('button', { name: /^Home$/i })).toBeVisible()
  })

  test('global nav tabs navigate to Health and back via Home', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    // Click Health top tab
    await page.locator('.nav-tabs__tab').filter({ hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Pipelines are no longer top-level nav tabs (cleanup 2026-04-30) —
    // return to OSS via Home → click the OSS card.
    await page
      .locator('.nav-tabs__tab')
      .filter({ hasText: /^Home$/ })
      .click()
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
  })
})

// ============ Tab 1: Repo Health ============

test.describe('Prod: Tab 1 — Repo Health', () => {
  test('loads repo health cards, empty state, or loading state', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const state = await waitForPanelState(
      page,
      '.repo-health-card',
      'No target repos',
      'Loading repos…'
    )

    if (state === 'data') {
      const firstCard = page.locator('.repo-health-card').first()
      await expect(firstCard.locator('.repo-health-card__slug')).toBeVisible()
    }
    // empty and loading states are also valid — the assertion in waitForPanelState
    // already confirmed one of the three states is showing
  })

  test('health scores section renders when cards are present', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const state = await waitForPanelState(
      page,
      '.repo-health-card',
      'No target repos',
      'Loading repos…'
    )
    if (state !== 'data') return

    const firstCard = page.locator('.repo-health-card').first()
    await expect(firstCard.locator('.repo-health-card__scores')).toBeVisible()
  })

  test('dossier sections are expandable when present', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const state = await waitForPanelState(
      page,
      '.repo-health-card',
      'No target repos',
      'Loading repos…'
    )
    if (state !== 'data') return

    const toggles = page.locator('.repo-health-card__section-toggle')
    if ((await toggles.count()) === 0) return

    // Expand first section
    await toggles.first().click()
    await expect(page.locator('.repo-health-card__section-content').first()).toBeVisible({
      timeout: 5000
    })

    // Collapse
    await toggles.first().click()
    await expect(page.locator('.repo-health-card__section-content').first()).not.toBeVisible()
  })

  test('Re-scrape button triggers API call', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const state = await waitForPanelState(
      page,
      '.repo-health-card',
      'No target repos',
      'Loading repos…'
    )
    if (state !== 'data') return

    const rescrapeBtn = page.getByRole('button', { name: /Re-scrape/i }).first()
    await expect(rescrapeBtn).toBeVisible()

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/tenhands/api/oss/refresh-target') && req.method() === 'POST',
      { timeout: ACTION_TIMEOUT }
    )
    await rescrapeBtn.click()
    const req = await requestPromise
    expect(req).toBeTruthy()
  })

  test('Re-compute button triggers API call', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const state = await waitForPanelState(
      page,
      '.repo-health-card',
      'No target repos',
      'Loading repos…'
    )
    if (state !== 'data') return

    const recomputeBtn = page.getByRole('button', { name: /Re-compute/i }).first()
    await expect(recomputeBtn).toBeVisible()

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/tenhands/api/oss/compute-target') && req.method() === 'POST',
      { timeout: ACTION_TIMEOUT }
    )
    await recomputeBtn.click()
    const req = await requestPromise
    expect(req).toBeTruthy()
  })
})

// ============ Tab 2: Fork & Assign ============

test.describe('Prod: Tab 2 — Fork & Assign', () => {
  test('loads scored issues table, empty state, or loading state', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )

    if (state === 'data') {
      await expect(page.locator('th').filter({ hasText: 'Repo' }).first()).toBeVisible()
      await expect(page.locator('th').filter({ hasText: 'CVS' }).first()).toBeVisible()
      await expect(page.locator('th').filter({ hasText: 'Tier' }).first()).toBeVisible()
    }
  })

  test('filter dropdowns are present and functional', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const filterSelects = page.locator('.filter-select')
    if ((await filterSelects.count()) === 0) return

    // Change the first filter (CVS Tier) and verify no crash
    const tierFilter = filterSelects.first()
    await tierFilter.selectOption('go')
    await tierFilter.selectOption('all')
  })

  test('Select All / Select None buttons work when recommended issues present', async ({
    page
  }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    // Select All/None are in the Recommended section
    const recommendedSection = page.locator('.stage-section').filter({ hasText: 'Recommended' })
    if (!(await recommendedSection.isVisible({ timeout: 3000 }).catch(() => false))) return

    const checkboxes = recommendedSection.locator('.data-table input[type="checkbox"]')
    const checkboxCount = await checkboxes.count()
    if (checkboxCount === 0) return

    // Select All
    await page.getByRole('button', { name: /^Select All$/i }).click()
    for (let i = 0; i < Math.min(checkboxCount, 3); i++) {
      await expect(checkboxes.nth(i)).toBeChecked()
    }

    // Select None
    await page.getByRole('button', { name: /^Select None$/i }).click()
    for (let i = 0; i < Math.min(checkboxCount, 3); i++) {
      await expect(checkboxes.nth(i)).not.toBeChecked()
    }
  })

  test('individual issue checkbox toggles correctly', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    // Checkboxes are in the Recommended section
    const recommendedSection = page.locator('.stage-section').filter({ hasText: 'Recommended' })
    if (!(await recommendedSection.isVisible({ timeout: 3000 }).catch(() => false))) return

    const checkboxes = recommendedSection.locator('.data-table input[type="checkbox"]')
    if ((await checkboxes.count()) === 0) return

    const firstCheckbox = checkboxes.first()
    await firstCheckbox.check()
    await expect(firstCheckbox).toBeChecked()
    await firstCheckbox.uncheck()
    await expect(firstCheckbox).not.toBeChecked()
  })

  test('Dossier button opens dossier panel when issues present', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const dossierBtn = page.getByRole('button', { name: /Dossier/i }).first()
    if (!(await dossierBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await dossierBtn.click()
    await expect(page.locator('.dossier-panel')).toBeVisible({ timeout: ACTION_TIMEOUT })
  })

  test('recommended section renders with batch controls when high-tier issues exist', async ({
    page
  }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    // Recommended section is conditional
    const recommendedSection = page.locator('.stage-section').filter({ hasText: 'Recommended' })
    if (!(await recommendedSection.isVisible({ timeout: 3000 }).catch(() => false))) return

    // Should have a table with checkboxes
    const recTable = recommendedSection.locator('.data-table')
    await expect(recTable).toBeVisible()
    const checkboxes = recTable.locator('input[type="checkbox"]')
    expect(await checkboxes.count()).toBeGreaterThan(0)

    // Should have Select All/None/Assign Selected buttons
    await expect(page.getByRole('button', { name: /^Select All$/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /^Select None$/i })).toBeVisible()
    await expect(page.getByRole('button', { name: /Assign Selected/i })).toBeVisible()
  })

  test('tier badges have valid CSS modifier classes', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const badges = page.locator('.data-table .badge')
    const count = await badges.count()
    if (count === 0) return

    for (let i = 0; i < Math.min(count, 5); i++) {
      const classList = await badges.nth(i).getAttribute('class')
      expect(classList).toMatch(/badge--(success|primary|warning|danger|secondary)/)
    }
  })

  test('issue title links have valid href and target attributes', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const issueLinks = page.locator('.data-table .issue-link')
    const count = await issueLinks.count()
    if (count === 0) return

    // Validate up to 3 links
    for (let i = 0; i < Math.min(count, 3); i++) {
      const link = issueLinks.nth(i)
      const href = await link.getAttribute('href')
      expect(href).toMatch(/^https:\/\/github\.com\//)
      await expect(link).toHaveAttribute('target', '_blank')
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    }
  })

  test('Show More pagination button loads additional rows', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    // Find the All Issues section
    const allIssuesSection = page.locator('.stage-section').filter({ hasText: 'All Issues' })
    if (!(await allIssuesSection.isVisible({ timeout: 3000 }).catch(() => false))) return

    const showMoreBtn = page.getByRole('button', { name: /Show More/i })
    if (!(await showMoreBtn.isVisible({ timeout: 3000 }).catch(() => false))) return

    // Count rows before clicking Show More
    const rowsBefore = await allIssuesSection.locator('.data-table tbody tr').count()

    // Click Show More — wait for row count to increase
    await showMoreBtn.click()
    await expect(allIssuesSection.locator('.data-table tbody tr').nth(rowsBefore)).toBeVisible({
      timeout: 5000
    })
  })

  test('Dossier panel tabs are clickable and switch content', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const dossierBtn = page.getByRole('button', { name: /Dossier/i }).first()
    if (!(await dossierBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await dossierBtn.click()
    await expect(page.locator('.dossier-panel')).toBeVisible({ timeout: ACTION_TIMEOUT })

    // Wait for loading to finish
    const tabsContainer = page.locator('.dossier-panel__tabs')
    await expect(tabsContainer.or(page.locator('.dossier-panel__error'))).toBeVisible({
      timeout: ACTION_TIMEOUT
    })

    // If error (aggregator down), close and return
    if (
      await page
        .locator('.dossier-panel__error')
        .isVisible()
        .catch(() => false)
    ) {
      await page.locator('.dossier-panel').getByRole('button', { name: /Close/i }).click()
      return
    }

    // Get all available tabs
    const tabs = page.locator('.dossier-tab')
    const tabCount = await tabs.count()
    if (tabCount === 0) return

    // Click each tab and verify it becomes active
    for (let i = 0; i < tabCount; i++) {
      await tabs.nth(i).click()
      await expect(tabs.nth(i)).toHaveClass(/dossier-tab--active/)
      // Content area should be visible
      await expect(page.locator('.dossier-panel__content')).toBeVisible()
    }

    // Close the panel
    await page.locator('.dossier-panel').getByRole('button', { name: /Close/i }).click()
    await expect(page.locator('.dossier-panel')).not.toBeVisible()
  })

  test('Dossier panel closes when clicking overlay background', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const dossierBtn = page.getByRole('button', { name: /Dossier/i }).first()
    if (!(await dossierBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await dossierBtn.click()
    await expect(page.locator('.dossier-panel')).toBeVisible({ timeout: ACTION_TIMEOUT })

    // Click the overlay (outside the panel) to close
    await page.locator('.dossier-overlay').click({ position: { x: 10, y: 10 } })
    await expect(page.locator('.dossier-panel')).not.toBeVisible({ timeout: 5000 })
  })

  test('all three filter dropdowns cycle through options without errors', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues…'
    )
    if (state !== 'data') return

    const filterSelects = page.locator('.filter-select')
    const filterCount = await filterSelects.count()
    if (filterCount < 3) return

    // Cycle CVS Tier filter
    await filterSelects.nth(0).selectOption('likely')
    await filterSelects.nth(0).selectOption('maybe')
    await filterSelects.nth(0).selectOption('risky')
    await filterSelects.nth(0).selectOption('all')

    // Cycle Complexity filter
    await filterSelects.nth(1).selectOption('low')
    await filterSelects.nth(1).selectOption('medium')
    await filterSelects.nth(1).selectOption('high')
    await filterSelects.nth(1).selectOption('all')

    // Cycle Lifecycle filter
    await filterSelects.nth(2).selectOption('fresh')
    await filterSelects.nth(2).selectOption('triaged')
    await filterSelects.nth(2).selectOption('accepted')
    await filterSelects.nth(2).selectOption('stale')
    await filterSelects.nth(2).selectOption('all')
  })
})

// ============ Tab 3: Pipeline Runs ============

test.describe('Prod: Tab 3 — Pipeline Runs', () => {
  test('loads pipeline runs or shows empty state', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )

    if (state === 'data') {
      await expect(page.locator('.metric-card__label').filter({ hasText: 'Total' })).toBeVisible()
    }
  })

  test('metric cards show Total, In Progress, Completed', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    await expect(page.locator('.metric-card__label').filter({ hasText: 'Total' })).toBeVisible()
    await expect(
      page.locator('.metric-card__label').filter({ hasText: 'In Progress' })
    ).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Completed' })).toBeVisible()
  })

  test('progress bars render when assignments exist', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const progressBars = page.locator('.pipeline-progress')
    if ((await progressBars.count()) === 0) return

    const segments = page.locator('.pipeline-progress__seg')
    expect(await segments.count()).toBeGreaterThan(0)
  })

  test('Report button opens modal with iframe', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const reportBtn = page.getByRole('button', { name: /^Report$/i }).first()
    if (!(await reportBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await reportBtn.click()
    await expect(page.locator('.report-modal')).toBeVisible({ timeout: ACTION_TIMEOUT })
    await expect(page.locator('.report-modal__iframe')).toBeVisible()

    const src = await page.locator('.report-modal__iframe').getAttribute('src')
    expect(src).toContain('/tenhands/api/oss/issue-report/')

    // Close the modal
    await page.locator('.report-modal__header').getByRole('button', { name: /Close/i }).click()
    await expect(page.locator('.report-modal')).not.toBeVisible()
  })

  test('status badges have valid CSS modifier classes', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const badges = page.locator('.data-table .badge')
    const count = await badges.count()
    if (count === 0) return

    for (let i = 0; i < Math.min(count, 5); i++) {
      const classList = await badges.nth(i).getAttribute('class')
      expect(classList).toMatch(/badge--(success|primary|warning|danger|secondary)/)
    }
  })

  test('assignment rows show origin repo and issue number', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const tableRows = page.locator('.data-table tbody tr')
    if ((await tableRows.count()) === 0) return

    const firstRow = tableRows.first()
    await expect(firstRow.locator('.repo-link')).toBeVisible()
    // Issue number displayed as #N
    await expect(firstRow.locator('td', { hasText: /^#\d+$/ })).toBeVisible()
  })

  test('Advance button triggers advance API when non-complete assignment exists', async ({
    page
  }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const advanceBtn = page.getByRole('button', { name: /^Advance$/i }).first()
    if (!(await advanceBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/tenhands/api/oss/advance-pipeline') && req.method() === 'POST',
      { timeout: ACTION_TIMEOUT }
    )
    await advanceBtn.click()
    const req = await requestPromise
    expect(req).toBeTruthy()
  })

  test('Signoff button triggers signoff API when complete assignment exists', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const signoffBtn = page.getByRole('button', { name: /^Signoff$/i }).first()
    if (!(await signoffBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/tenhands/api/oss/signoff') && req.method() === 'POST',
      { timeout: ACTION_TIMEOUT }
    )
    await signoffBtn.click()
    const req = await requestPromise
    expect(req).toBeTruthy()
  })

  test('Report modal closes when clicking overlay background', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs…'
    )
    if (state !== 'data') return

    const reportBtn = page.getByRole('button', { name: /^Report$/i }).first()
    if (!(await reportBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await reportBtn.click()
    await expect(page.locator('.report-modal')).toBeVisible({ timeout: ACTION_TIMEOUT })

    // Click the modal overlay (outside the content) to close
    await page.locator('.report-modal').click({ position: { x: 10, y: 10 } })
    await expect(page.locator('.report-modal')).not.toBeVisible({ timeout: 5000 })
  })
})

// ============ Tab 4: Review ============

test.describe('Prod: Tab 4 — Review', () => {
  test('loads submitted PRs or shows empty state', async ({ page }) => {
    await navigateToOSSTab(page, 'Review')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No submitted PRs',
      'Polling upstream PR statuses…'
    )

    if (state === 'data') {
      await expect(page.locator('.metric-card__label').filter({ hasText: 'Total' })).toBeVisible()
    }
  })

  test('metric cards show Total, Open, Merged, Closed', async ({ page }) => {
    await navigateToOSSTab(page, 'Review')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No submitted PRs',
      'Polling upstream PR statuses…'
    )
    if (state !== 'data') return

    await expect(page.locator('.metric-card__label').filter({ hasText: 'Total' })).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Open' })).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Merged' })).toBeVisible()
    await expect(page.locator('.metric-card__label').filter({ hasText: 'Closed' })).toBeVisible()
  })

  test('PR table has correct column headers when data present', async ({ page }) => {
    await navigateToOSSTab(page, 'Review')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No submitted PRs',
      'Polling upstream PR statuses…'
    )
    if (state !== 'data') return

    const table = page.locator('.data-table')
    if (!(await table.isVisible({ timeout: 5000 }).catch(() => false))) return

    await expect(page.locator('th').filter({ hasText: 'Origin Repo' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'PR' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Title' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Status' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Comments' })).toBeVisible()
    await expect(page.locator('th').filter({ hasText: 'Labels' })).toBeVisible()
  })

  test('status badges have valid states', async ({ page }) => {
    await navigateToOSSTab(page, 'Review')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No submitted PRs',
      'Polling upstream PR statuses…'
    )
    if (state !== 'data') return

    const badges = page.locator('.data-table .badge')
    const count = await badges.count()
    if (count === 0) return

    for (let i = 0; i < Math.min(count, 5); i++) {
      const text = await badges.nth(i).textContent()
      expect(text).toMatch(/Open|Merged|Closed|Approved|Changes Requested/i)
    }
  })

  test('Refresh Status button triggers poll API', async ({ page }) => {
    await navigateToOSSTab(page, 'Review')

    const refreshBtn = page.getByRole('button', { name: /Refresh Status/i })
    if (!(await refreshBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/tenhands/api/oss/poll-submitted-prs') && req.method() === 'POST',
      { timeout: ACTION_TIMEOUT }
    )
    await refreshBtn.click()
    const req = await requestPromise
    expect(req).toBeTruthy()
  })

  test('PR number links have valid href and target attributes', async ({ page }) => {
    await navigateToOSSTab(page, 'Review')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No submitted PRs',
      'Polling upstream PR statuses…'
    )
    if (state !== 'data') return

    const prLinks = page.locator('.data-table .issue-link')
    const count = await prLinks.count()
    if (count === 0) return

    // Validate up to 3 PR links
    for (let i = 0; i < Math.min(count, 3); i++) {
      const link = prLinks.nth(i)
      const href = await link.getAttribute('href')
      expect(href).toMatch(/^https:\/\/github\.com\//)
      await expect(link).toHaveAttribute('target', '_blank')
      await expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    }
  })
})

// ============ Global Repo Filter ============

test.describe('Prod: Global Repo Filter', () => {
  test('filter popover opens and closes', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const trigger = page.locator('.repo-filter-trigger')
    if (!(await trigger.isVisible({ timeout: 5000 }).catch(() => false))) return

    await trigger.click()
    await expect(page.locator('.repo-filter-popover__panel')).toBeVisible()

    await trigger.click()
    await expect(page.locator('.repo-filter-popover__panel')).not.toBeVisible()
  })

  test('filter trigger shows repo count', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const trigger = page.locator('.repo-filter-trigger')
    if (!(await trigger.isVisible({ timeout: 5000 }).catch(() => false))) return

    await expect(trigger).toContainText('Repos')
    await expect(trigger).toContainText('of')
  })

  test('search filters the repo list', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const trigger = page.locator('.repo-filter-trigger')
    if (!(await trigger.isVisible({ timeout: 5000 }).catch(() => false))) return

    await trigger.click()
    const searchInput = page.locator('.repo-filter-popover__search input')
    await searchInput.fill('zzz-nonexistent-repo-9999')

    // Should show "No matches" or zero items
    const items = page.locator('.repo-filter-popover__item')
    const count = await items.count()
    if (count === 0) {
      await expect(page.locator('.repo-filter-popover__empty')).toBeVisible()
    }
  })

  test('All/None buttons toggle checkboxes', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const trigger = page.locator('.repo-filter-trigger')
    if (!(await trigger.isVisible({ timeout: 5000 }).catch(() => false))) return

    await trigger.click()

    const checkboxes = page.locator('.repo-filter-popover__item input[type="checkbox"]')
    const count = await checkboxes.count()
    if (count === 0) return

    // Click None — all unchecked
    await page
      .locator('.repo-filter-popover__actions')
      .getByRole('button', { name: 'None' })
      .click()
    for (let i = 0; i < Math.min(count, 3); i++) {
      await expect(checkboxes.nth(i)).not.toBeChecked()
    }

    // Click All — all checked
    await page.locator('.repo-filter-popover__actions').getByRole('button', { name: 'All' }).click()
    for (let i = 0; i < Math.min(count, 3); i++) {
      await expect(checkboxes.nth(i)).toBeChecked()
    }
  })

  test('filter footer shows selected count', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const trigger = page.locator('.repo-filter-trigger')
    if (!(await trigger.isVisible({ timeout: 5000 }).catch(() => false))) return

    await trigger.click()
    const footer = page.locator('.repo-filter-popover__footer')
    await expect(footer).toBeVisible()
    await expect(footer).toContainText('of')
    await expect(footer).toContainText('selected')
  })

  test('individual repo checkbox toggles correctly', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const trigger = page.locator('.repo-filter-trigger')
    if (!(await trigger.isVisible({ timeout: 5000 }).catch(() => false))) return

    await trigger.click()

    const checkboxes = page.locator('.repo-filter-popover__item input[type="checkbox"]')
    const count = await checkboxes.count()
    if (count === 0) return

    const firstCheckbox = checkboxes.first()
    const wasChecked = await firstCheckbox.isChecked()

    // Toggle it
    await firstCheckbox.click()
    if (wasChecked) {
      await expect(firstCheckbox).not.toBeChecked()
    } else {
      await expect(firstCheckbox).toBeChecked()
    }

    // Toggle back
    await firstCheckbox.click()
    if (wasChecked) {
      await expect(firstCheckbox).toBeChecked()
    } else {
      await expect(firstCheckbox).not.toBeChecked()
    }
  })
})

// ============ Progress Log ============

test.describe('Prod: Progress Log', () => {
  test('activity log appears after triggering an action and Clear button works', async ({
    page
  }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    // Trigger an action that produces a log entry — Refresh All
    const refreshBtn = page.getByRole('button', { name: 'Refresh All' })
    await expect(refreshBtn).toBeVisible()
    await refreshBtn.click()

    // Wait for refresh to complete (log entries appear during/after)
    await expect(page.getByRole('button', { name: 'Refresh All' })).toBeVisible({
      timeout: 50_000
    })

    // The progress log might be visible if any actions were taken in this session
    const progressLog = page.locator('.progress-log')
    if (!(await progressLog.isVisible({ timeout: 5000 }).catch(() => false))) return

    // Should show Activity Log title
    await expect(progressLog.locator('.progress-log-title')).toContainText('Activity Log')

    // Clear button should exist and work
    const clearBtn = progressLog.locator('.progress-log-clear')
    await expect(clearBtn).toBeVisible()
    await clearBtn.click()

    // After clearing, the progress log should disappear (renders null when empty)
    await expect(progressLog).not.toBeVisible({ timeout: 5000 })
  })
})

// ============ Health View ============

test.describe('Prod: Health View', () => {
  test('Health view loads with stats cards', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Navigate to OSS first to get nav tabs, then click Health
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible({
      timeout: LOAD_TIMEOUT
    })

    await page.locator('.nav-tabs__tab').filter({ hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Stats cards should be present (they render immediately with count=0, then update)
    await expect(page.locator('.stat-card__label').filter({ hasText: 'Total Runs' })).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
    await expect(page.locator('.stat-card__label').filter({ hasText: 'Successful' })).toBeVisible()
    await expect(page.locator('.stat-card__label').filter({ hasText: 'Failed' })).toBeVisible()
    await expect(page.locator('.stat-card__label').filter({ hasText: 'In Progress' })).toBeVisible()
  })

  test('Health view Refresh button works', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
    await page.locator('.nav-tabs__tab').filter({ hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Wait for initial load
    const refreshBtn = page.locator('.health-view').getByRole('button', { name: /Refresh/i })
    await expect(refreshBtn).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Wait until button is not disabled (initial load finished)
    await expect(refreshBtn).toBeEnabled({ timeout: LOAD_TIMEOUT })

    await refreshBtn.click()
    // Should show "Refreshing…" then go back to "Refresh"
    await expect(
      page.locator('.health-view').getByRole('button', { name: /Refreshing/i })
    ).toBeVisible({ timeout: 5000 })
    await expect(
      page.locator('.health-view').getByRole('button', { name: /^Refresh$/i })
    ).toBeVisible({ timeout: LOAD_TIMEOUT })
  })

  test('Health view filter dropdowns work', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
    await page.locator('.nav-tabs__tab').filter({ hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Wait for data
    await expect(page.locator('.stat-card').first()).toBeVisible({ timeout: LOAD_TIMEOUT })

    const filterSelects = page.locator('.health-view .filter-select')
    const filterCount = await filterSelects.count()
    if (filterCount < 2) return

    // Cycle VibeCheck Status filter
    await filterSelects.nth(0).selectOption('vc-installed')
    await filterSelects.nth(0).selectOption('vc-not-installed')
    await filterSelects.nth(0).selectOption('all')

    // Cycle Run Status filter
    await filterSelects.nth(1).selectOption('success')
    await filterSelects.nth(1).selectOption('failure')
    await filterSelects.nth(1).selectOption('all')
  })

  test('Health view Show Failed quick filter button works', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
    await page.locator('.nav-tabs__tab').filter({ hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Wait for data
    await expect(page.locator('.stat-card').first()).toBeVisible({ timeout: LOAD_TIMEOUT })

    const showFailedBtn = page.locator('.health-view').getByRole('button', { name: /Show Failed/i })
    if (!(await showFailedBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await showFailedBtn.click()
    // Run Status filter should now be set to "failure"
    const statusFilter = page.locator('.health-view .filter-select').nth(1)
    await expect(statusFilter).toHaveValue('failure')
  })

  test('Health view workflow table links have valid href', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=TenHands')).toBeVisible({ timeout: LOAD_TIMEOUT })
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(
      page.locator('.stage-tab__label').filter({ hasText: 'Pipeline Runs' })
    ).toBeVisible({
      timeout: LOAD_TIMEOUT
    })
    await page.locator('.nav-tabs__tab').filter({ hasText: 'Health' }).click()
    await expect(page.locator('.health-view')).toBeVisible({ timeout: LOAD_TIMEOUT })

    // Wait for table
    const table = page.locator('.health-view .data-table')
    if (!(await table.isVisible({ timeout: LOAD_TIMEOUT }).catch(() => false))) return

    const actionLinks = table.locator('a.btn--ghost')
    const count = await actionLinks.count()
    if (count === 0) return

    // Validate up to 3 links
    for (let i = 0; i < Math.min(count, 3); i++) {
      const link = actionLinks.nth(i)
      const href = await link.getAttribute('href')
      expect(href).toMatch(/^https:\/\/github\.com\//)
      await expect(link).toHaveAttribute('target', '_blank')
    }
  })
})

// ============ Cross-Tab Network Audit ============

test.describe('Prod: Cross-Tab Network Audit', () => {
  test('full tab traversal produces no non-2xx OSS API responses', async ({ page, auditTrail }) => {
    await navigateToOSSTab(page, 'Repo Health')
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await page.locator('.stage-tab').filter({ hasText: 'Fork & Assign' }).click()
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await page.locator('.stage-tab').filter({ hasText: 'Pipeline Runs' }).click()
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await page.locator('.stage-tab').filter({ hasText: 'Review' }).click()
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    // Assert no failed OSS API requests
    const failedOSS = auditTrail.network.filter(n => n.isOSSAPI && n.isError)
    if (failedOSS.length > 0) {
      const summary = failedOSS.map(f => `  ${f.method} ${f.url} => ${f.status}`).join('\n')
      throw new Error(`${failedOSS.length} OSS API request(s) returned non-2xx:\n${summary}`)
    }

    // Sanity check: verify we captured some OSS API requests
    const ossRequests = auditTrail.network.filter(n => n.isOSSAPI)
    expect(ossRequests.length).toBeGreaterThan(0)
  })

  test('all OSS API responses contain { success: true }', async ({ page, auditTrail }) => {
    await navigateToOSSTab(page, 'Repo Health')
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await page.locator('.stage-tab').filter({ hasText: 'Fork & Assign' }).click()
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await page.locator('.stage-tab').filter({ hasText: 'Pipeline Runs' }).click()
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    await page.locator('.stage-tab').filter({ hasText: 'Review' }).click()
    await page.waitForLoadState('networkidle', { timeout: 15_000 })

    const ossResponses = auditTrail.network.filter(n => n.isOSSAPI && n.responseBody)
    const malformed: string[] = []

    for (const entry of ossResponses) {
      try {
        const body = JSON.parse(entry.responseBody!) as { success?: boolean }
        if (body.success !== true) {
          malformed.push(`${entry.method} ${entry.url} => success=${String(body.success)}`)
        }
      } catch {
        // Non-JSON responses (e.g., HTML reports) are fine
        if (!entry.url.includes('/issue-report/')) {
          malformed.push(`${entry.method} ${entry.url} => non-JSON response`)
        }
      }
    }

    if (malformed.length > 0) {
      throw new Error(
        `${malformed.length} OSS API response(s) did not return { success: true }:\n  ${malformed.join('\n  ')}`
      )
    }
  })
})
