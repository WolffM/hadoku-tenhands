/**
 * Production E2E Tests — OSS Recon Pipeline
 *
 * Hits the REAL Flask backend (port 5000) via Vite dev server (port 5175).
 * No route interception — all API calls go to the real aggregator + gh CLI.
 *
 * Requirements:
 *   - Flask backend running on port 5000 with .env loaded
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
  await expect(page.locator('text=VibeDispatch')).toBeVisible({ timeout: LOAD_TIMEOUT })

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
  const refreshingBtn = page.getByRole('button', { name: 'Refreshing...' })
  await expect(refreshAllBtn.or(refreshingBtn)).toBeVisible({ timeout: LOAD_TIMEOUT })

  // If still refreshing, wait for it to finish
  if (await refreshingBtn.isVisible().catch(() => false)) {
    await expect(refreshAllBtn).toBeVisible({ timeout: LOAD_TIMEOUT })
  }

  // Navigate to the requested tab
  if (tabLabel !== 'Pipeline Runs') {
    await page.locator('.stage-tab').filter({ hasText: tabLabel }).click()
    // Wait for tab content to settle
    await page.waitForTimeout(2000)
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
    const response = await request.get('/dispatch/api/healthcheck')
    expect(response.ok()).toBeTruthy()
    const data = (await response.json()) as { success: boolean; owner: string }
    expect(data.success).toBe(true)
    expect(data.owner).toBeTruthy()
  })

  test('gh CLI is authenticated', async ({ request }) => {
    const response = await request.get('/dispatch/api/oss/debug/gh-health')
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
    const response = await request.get('/dispatch/api/oss/debug/aggregator-health')
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
    await expect(page.locator('text=VibeDispatch')).toBeVisible({ timeout: LOAD_TIMEOUT })
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await expect(
      page.locator('.pipeline-select-card').filter({ hasText: 'OSS Contribution Pipeline' })
    ).toBeVisible()
  })

  test('can navigate to OSS pipeline and see all 4 tabs', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('text=VibeDispatch')).toBeVisible({ timeout: LOAD_TIMEOUT })

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
      await page.waitForTimeout(2000)
      await expect(page.locator('.stage-tab--active')).toBeVisible()
    }
  })

  test('Refresh All button works', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    // After navigateToOSSTab, button should say "Refresh All" (load completed)
    const refreshBtn = page.getByRole('button', { name: 'Refresh All' })
    await expect(refreshBtn).toBeVisible()
    await refreshBtn.click()

    // Should show "Refreshing..." then go back to "Refresh All"
    await expect(page.getByRole('button', { name: 'Refreshing...' })).toBeVisible({
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
})

// ============ Tab 1: Repo Health ============

test.describe('Prod: Tab 1 — Repo Health', () => {
  test('loads repo health cards, empty state, or loading state', async ({ page }) => {
    await navigateToOSSTab(page, 'Repo Health')

    const state = await waitForPanelState(
      page,
      '.repo-health-card',
      'No target repos',
      'Loading repos...'
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
      'Loading repos...'
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
      'Loading repos...'
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
      'Loading repos...'
    )
    if (state !== 'data') return

    const rescrapeBtn = page.getByRole('button', { name: /Re-scrape/i }).first()
    await expect(rescrapeBtn).toBeVisible()

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/dispatch/api/oss/refresh-target') && req.method() === 'POST',
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
      'Loading repos...'
    )
    if (state !== 'data') return

    const recomputeBtn = page.getByRole('button', { name: /Re-compute/i }).first()
    await expect(recomputeBtn).toBeVisible()

    const requestPromise = page.waitForRequest(
      req => req.url().includes('/dispatch/api/oss/compute-target') && req.method() === 'POST',
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
      'Loading scored issues...'
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
      'Loading scored issues...'
    )
    if (state !== 'data') return

    const filterSelects = page.locator('.filter-select')
    if ((await filterSelects.count()) === 0) return

    // Change the first filter (CVS Tier) and verify no crash
    const tierFilter = filterSelects.first()
    await tierFilter.selectOption('go')
    await page.waitForTimeout(500)
    await tierFilter.selectOption('all')
    await page.waitForTimeout(500)
  })

  test('Select All / Select None buttons work when issues present', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues...'
    )
    if (state !== 'data') return

    const checkboxes = page.locator('.data-table input[type="checkbox"]')
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
      'Loading scored issues...'
    )
    if (state !== 'data') return

    const checkboxes = page.locator('.data-table input[type="checkbox"]')
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
      'Loading scored issues...'
    )
    if (state !== 'data') return

    const dossierBtn = page.getByRole('button', { name: /Dossier/i }).first()
    if (!(await dossierBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await dossierBtn.click()
    await expect(page.locator('.dossier-panel')).toBeVisible({ timeout: ACTION_TIMEOUT })
  })

  test('recommended section renders when high-tier issues exist', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues...'
    )
    if (state !== 'data') return

    // Recommended section is conditional
    const recommendedSection = page.locator('text=Recommended').first()
    if (await recommendedSection.isVisible({ timeout: 3000 }).catch(() => false)) {
      const recTable = page
        .locator('.stage-section')
        .filter({ hasText: 'Recommended' })
        .locator('.data-table')
      await expect(recTable).toBeVisible()
    }
  })

  test('tier badges have valid CSS modifier classes', async ({ page }) => {
    await navigateToOSSTab(page, 'Fork & Assign')

    const state = await waitForPanelState(
      page,
      '.data-table',
      'No scored issues',
      'Loading scored issues...'
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
})

// ============ Tab 3: Pipeline Runs ============

test.describe('Prod: Tab 3 — Pipeline Runs', () => {
  test('loads pipeline runs or shows empty state', async ({ page }) => {
    await navigateToOSSTab(page, 'Pipeline Runs')

    const state = await waitForPanelState(
      page,
      '.metric-card',
      'No pipeline runs',
      'Loading pipeline runs...'
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
      'Loading pipeline runs...'
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
      'Loading pipeline runs...'
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
      'Loading pipeline runs...'
    )
    if (state !== 'data') return

    const reportBtn = page.getByRole('button', { name: /^Report$/i }).first()
    if (!(await reportBtn.isVisible({ timeout: 5000 }).catch(() => false))) return

    await reportBtn.click()
    await expect(page.locator('.report-modal')).toBeVisible({ timeout: ACTION_TIMEOUT })
    await expect(page.locator('.report-modal__iframe')).toBeVisible()

    const src = await page.locator('.report-modal__iframe').getAttribute('src')
    expect(src).toContain('/dispatch/api/oss/issue-report/')

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
      'Loading pipeline runs...'
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
      'Loading pipeline runs...'
    )
    if (state !== 'data') return

    const tableRows = page.locator('.data-table tbody tr')
    if ((await tableRows.count()) === 0) return

    const firstRow = tableRows.first()
    await expect(firstRow.locator('.repo-link')).toBeVisible()
    // Issue number displayed as #N
    await expect(firstRow.locator('td', { hasText: /^#\d+$/ })).toBeVisible()
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
      'Polling upstream PR statuses...'
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
      'Polling upstream PR statuses...'
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
      'Polling upstream PR statuses...'
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
      'Polling upstream PR statuses...'
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
      req => req.url().includes('/dispatch/api/oss/poll-submitted-prs') && req.method() === 'POST',
      { timeout: ACTION_TIMEOUT }
    )
    await refreshBtn.click()
    const req = await requestPromise
    expect(req).toBeTruthy()
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
})

// ============ Cross-Tab Network Audit ============

test.describe('Prod: Cross-Tab Network Audit', () => {
  test('full tab traversal produces no non-2xx OSS API responses', async ({ page, auditTrail }) => {
    await navigateToOSSTab(page, 'Repo Health')
    await page.waitForTimeout(3000)

    await page.locator('.stage-tab').filter({ hasText: 'Fork & Assign' }).click()
    await page.waitForTimeout(3000)

    await page.locator('.stage-tab').filter({ hasText: 'Pipeline Runs' }).click()
    await page.waitForTimeout(3000)

    await page.locator('.stage-tab').filter({ hasText: 'Review' }).click()
    await page.waitForTimeout(3000)

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
    await page.waitForTimeout(3000)

    await page.locator('.stage-tab').filter({ hasText: 'Fork & Assign' }).click()
    await page.waitForTimeout(3000)

    await page.locator('.stage-tab').filter({ hasText: 'Pipeline Runs' }).click()
    await page.waitForTimeout(3000)

    await page.locator('.stage-tab').filter({ hasText: 'Review' }).click()
    await page.waitForTimeout(3000)

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
