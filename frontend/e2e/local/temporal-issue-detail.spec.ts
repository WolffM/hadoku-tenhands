/**
 * Crimson-Kitty IssueDetail e2e (phase-1-plan.md step 2.5).
 *
 * Navigates into the temporal view, selects a batch and then an issue, and
 * asserts every section of `IssueDetail` renders against mocked API data.
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'
import { mockTemporalAPIs, mockTemporalBatchDetail } from '../fixtures/temporal-mocks'

test.describe('Temporal issue detail', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await mockTemporalAPIs(page)
    await page.goto('/?key=test-key')
    await page.locator('.pipeline-select-card').filter({ hasText: 'Crimson-Kitty' }).click()
    await expect(page.getByTestId('temporal-pipeline-view')).toBeVisible()
  })

  test('shows header, timeline, gates, evidence, and events', async ({ page }) => {
    // Select the first batch
    await page.getByTestId('temporal-batch-button').first().click()
    await expect(page.getByTestId('temporal-issues-list')).toBeVisible()

    // Select the first issue in that batch
    const firstIssueId = mockTemporalBatchDetail.issues[0].issue_id
    await page.getByTestId('temporal-issue-button').filter({ hasText: firstIssueId }).click()

    const detail = page.getByTestId('temporal-issue-detail')
    await expect(detail).toBeVisible()

    // Header has the state badge
    const badge = detail.getByTestId('temporal-state-badge')
    await expect(badge).toBeVisible()

    // Timeline section with 3 mocked transitions
    const timeline = detail.getByTestId('temporal-issue-timeline')
    await expect(timeline).toBeVisible()
    await expect(timeline.getByTestId('temporal-transition')).toHaveCount(3)

    // Gates section with 3 mocked gate records
    const gates = detail.getByTestId('temporal-issue-gates')
    await expect(gates).toBeVisible()
    await expect(gates.getByTestId('temporal-gate-row')).toHaveCount(3)

    // Evidence section renders at least one EvidencePreview for the diff gate
    const evidence = detail.getByTestId('temporal-issue-evidence')
    await expect(evidence).toBeVisible()
    await expect(evidence.getByTestId('temporal-evidence-diff').first()).toBeVisible()

    // Events section renders the events list
    const events = detail.getByTestId('temporal-issue-events')
    await expect(events).toBeVisible()
    await expect(events.getByTestId('temporal-event').first()).toBeVisible()
  })
})
