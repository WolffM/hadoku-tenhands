/**
 * Crimson-Kitty PipelineInbox e2e (phase-1-plan.md step 2.6).
 *
 *   - Loads inbox with 3 mocked entries
 *   - approve / abort / retry each open a reason picker, and confirming it
 *     POSTs to the signal endpoint
 *   - Each decision, with its reason code, is recorded in
 *     `window.__temporalSignals`
 *
 * The decision button is not the send button: choosing approve/abort/retry
 * opens a reason picker and the POST happens on Confirm. That capture step
 * feeds the calibration corpus, so a test asserting only the decision would
 * pass while the reason silently went missing — every assertion below checks
 * the reason code that travelled with it.
 */

import { test, expect } from '../fixtures/base'
import type { Locator, Page } from '@playwright/test'
import { mockAllAPIs } from '../fixtures/api-mocks'
import {
  mockTemporalAPIs,
  mockTemporalInboxItems,
  type TemporalSignalCall
} from '../fixtures/temporal-mocks'

/** The last signal POST the mock recorded, or undefined if none yet. */
function lastSignal(page: Page) {
  return page.evaluate(
    () =>
      (
        (window as unknown as { __temporalSignals?: TemporalSignalCall[] }).__temporalSignals ?? []
      ).slice(-1)[0]
  )
}

/** Choose a decision on a row, then confirm it in the reason picker. */
async function decide(row: Locator, decision: 'approve' | 'abort' | 'retry') {
  await row.getByTestId(`temporal-inbox-${decision}`).click()
  const picker = row.getByTestId('temporal-inbox-reason-picker')
  await expect(picker).toBeVisible()
  await picker.getByTestId('temporal-inbox-reason-confirm').click()
}

test.describe('Temporal pipeline inbox', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await mockTemporalAPIs(page)
    await page.goto('/?key=test-key')
    await page.locator('.pipeline-select-card').filter({ hasText: 'Crimson-Kitty' }).click()
  })

  test('renders 3 inbox entries with action buttons', async ({ page }) => {
    const inbox = page.getByTestId('temporal-inbox')
    await expect(inbox).toBeVisible()
    await expect(inbox.getByTestId('temporal-inbox-row')).toHaveCount(mockTemporalInboxItems.length)
  })

  test('approve sends approve signal for the first row', async ({ page }) => {
    const firstRow = page.getByTestId('temporal-inbox-row').first()
    const expectedWorkflow = mockTemporalInboxItems[0].workflow_id
    await decide(firstRow, 'approve')

    await expect
      .poll(() => lastSignal(page))
      .toMatchObject({
        workflowId: expectedWorkflow,
        decision: 'approve',
        reasonCode: 'approve_clean'
      })
  })

  test('abort sends abort signal for the second row', async ({ page }) => {
    const row = page.getByTestId('temporal-inbox-row').nth(1)
    const expectedWorkflow = mockTemporalInboxItems[1].workflow_id
    await decide(row, 'abort')

    await expect
      .poll(() => lastSignal(page))
      .toMatchObject({
        workflowId: expectedWorkflow,
        decision: 'abort',
        reasonCode: 'abort_scope_mismatch'
      })
  })

  test('retry sends retry signal for the third row', async ({ page }) => {
    const row = page.getByTestId('temporal-inbox-row').nth(2)
    const expectedWorkflow = mockTemporalInboxItems[2].workflow_id
    await decide(row, 'retry')

    await expect
      .poll(() => lastSignal(page))
      .toMatchObject({
        workflowId: expectedWorkflow,
        decision: 'retry',
        reasonCode: 'retry_transient'
      })
  })

  test('choosing a decision sends nothing until it is confirmed', async ({ page }) => {
    const row = page.getByTestId('temporal-inbox-row').first()
    await row.getByTestId('temporal-inbox-abort').click()
    await expect(row.getByTestId('temporal-inbox-reason-picker')).toBeVisible()
    expect(await lastSignal(page)).toBeUndefined()

    // Cancel puts the row back where it was, still having sent nothing.
    await row.getByTestId('temporal-inbox-reason-cancel').click()
    await expect(row.getByTestId('temporal-inbox-reason-picker')).toHaveCount(0)
    await expect(row.getByTestId('temporal-inbox-abort')).toBeVisible()
    expect(await lastSignal(page)).toBeUndefined()
  })

  test('a chosen reason and its free text reach the signal endpoint', async ({ page }) => {
    const row = page.getByTestId('temporal-inbox-row').first()
    await row.getByTestId('temporal-inbox-abort').click()

    const picker = row.getByTestId('temporal-inbox-reason-picker')
    // `abort_other` is the one code that requires free text — Confirm stays
    // disabled until it is typed, which is the rule worth pinning down.
    await picker.getByTestId('temporal-inbox-reason-select').selectOption('abort_other')
    await expect(picker.getByTestId('temporal-inbox-reason-confirm')).toBeDisabled()

    await picker.getByTestId('temporal-inbox-reason-text').fill('patch reverted upstream')
    await picker.getByTestId('temporal-inbox-reason-confirm').click()

    await expect
      .poll(() => lastSignal(page))
      .toMatchObject({
        decision: 'abort',
        reasonCode: 'abort_other',
        reasonText: 'patch reverted upstream'
      })
  })

  // Phase 5.4 — operator signoff card variant.

  test('operator_signoff entry renders the signoff card variant', async ({ page }) => {
    // data-card-variant is set on the row element itself, so select by the
    // combined attribute selector rather than `filter({ has })` — `has`
    // only matches descendants, never the element it's called on.
    const signoffRow = page
      .locator('[data-testid="temporal-inbox-row"][data-card-variant="signoff"]')
      .first()
    // The 4th mock entry is the signoff one — the filter above should find
    // exactly one row with the signoff variant.
    await expect(signoffRow).toBeVisible()
    await expect(signoffRow).toHaveAttribute(
      'data-workflow-id',
      'issue-crimson-kitty-signoff-microsoft__terminal-5301'
    )

    // PR title surfaces inline
    await expect(signoffRow.getByTestId('temporal-inbox-pr-title')).toContainText(
      'Tab close button stops responding'
    )

    // Body excerpt surfaces inline (first 500 chars from the backend)
    await expect(signoffRow.getByTestId('temporal-inbox-pr-body-excerpt')).toContainText(
      'rebinds it on profile change'
    )

    // Preview link points at the fork PR and opens in a new tab
    const previewLink = signoffRow.getByTestId('temporal-inbox-preview-link')
    await expect(previewLink).toHaveAttribute(
      'href',
      'https://github.com/WolffM/microsoft-terminal/pull/9'
    )
    await expect(previewLink).toHaveAttribute('target', '_blank')

    // No Retry button on the signoff variant — only Approve & Abort
    await expect(signoffRow.getByTestId('temporal-inbox-retry')).toHaveCount(0)
    await expect(signoffRow.getByTestId('temporal-inbox-approve')).toContainText('Approve')
    await expect(signoffRow.getByTestId('temporal-inbox-abort')).toBeVisible()
  })

  test('approve on signoff card sends approve signal', async ({ page }) => {
    const signoffRow = page
      .locator('[data-testid="temporal-inbox-row"][data-card-variant="signoff"]')
      .first()
    const expectedWorkflow = 'issue-crimson-kitty-signoff-microsoft__terminal-5301'

    await decide(signoffRow, 'approve')

    await expect
      .poll(() => lastSignal(page))
      .toMatchObject({
        workflowId: expectedWorkflow,
        decision: 'approve',
        reasonCode: 'approve_clean'
      })
  })

  test('judge-defer rows still render with the legacy three-button layout', async ({ page }) => {
    // The first mocked entry (relevance gate) should render as a judge-defer
    // card, NOT a signoff card — confirms the gate-name branch leaves the
    // existing flow untouched.
    const judgeRow = page
      .locator('[data-testid="temporal-inbox-row"][data-card-variant="judge-defer"]')
      .first()
    await expect(judgeRow).toBeVisible()
    await expect(judgeRow.getByTestId('temporal-inbox-approve')).toBeVisible()
    await expect(judgeRow.getByTestId('temporal-inbox-abort')).toBeVisible()
    await expect(judgeRow.getByTestId('temporal-inbox-retry')).toBeVisible()
    // Signoff-only fields are absent
    await expect(judgeRow.getByTestId('temporal-inbox-preview-link')).toHaveCount(0)
    await expect(judgeRow.getByTestId('temporal-inbox-pr-body-excerpt')).toHaveCount(0)
  })
})
