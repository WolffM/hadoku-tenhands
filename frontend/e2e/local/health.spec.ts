/**
 * Health view — workflow runs across repos, with stat cards and filters.
 *
 * The stat counts are derived from the SAME fixture the view is fed, so the
 * expectations move with the data instead of being hand-copied numbers that
 * rot the moment someone adds a run.
 */

import { test, expect, type Page } from '../fixtures/base'
import { mockWorkflowRuns } from '../fixtures/data'

const total = mockWorkflowRuns.length
const success = mockWorkflowRuns.filter(r => r.conclusion === 'success').length
const failed = mockWorkflowRuns.filter(r => r.conclusion === 'failure').length
const inProgress = mockWorkflowRuns.filter(r => r.status === 'in_progress').length

/** Read a stat card by its label, so a reordering of the row does not fail. */
function statCard(page: Page, label: string) {
  return page.locator('.stat-card').filter({ hasText: label }).locator('.stat-card__value')
}

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Health', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Health Check' })).toBeVisible()
})

test.describe('stats', () => {
  test('counts every run the API returned', async ({ page }) => {
    await expect(statCard(page, 'Total Runs')).toHaveText(String(total))
    await expect(statCard(page, 'Successful')).toHaveText(String(success))
  })

  test('separates failures and in-flight runs', async ({ page }) => {
    // `conclusion: null` with `status: in_progress` must count as in-progress
    // and NOT as a failure — the distinction the pipeline actually cares about.
    await expect(statCard(page, 'Failed')).toHaveText(String(failed))
    await expect(statCard(page, 'In Progress')).toHaveText(String(inProgress))
  })
})

test.describe('runs table', () => {
  test('lists one row per run, with its repo and workflow', async ({ page }) => {
    // Scoped to the table body on purpose: the workflow names also appear as
    // <option>s in the filter dropdown, and a page-wide text match happily
    // resolves to a hidden one and then fails on visibility.
    const rows = page.locator('table.data-table tbody tr')
    await expect(rows).toHaveCount(total)

    for (const run of mockWorkflowRuns) {
      const row = rows.filter({ hasText: run.repo }).filter({ hasText: run.workflowName })
      await expect(row).toHaveCount(1)
    }
  })
})

test.describe('empty state', () => {
  test.use({
    apiOverrides: {
      'GET /api/global-workflow-runs': { success: true, runs: [], owner: 'test-user' }
    }
  })

  test('reports zeros rather than the previous data', async ({ page }) => {
    await expect(statCard(page, 'Total Runs')).toHaveText('0')
    await expect(statCard(page, 'Successful')).toHaveText('0')
  })
})
