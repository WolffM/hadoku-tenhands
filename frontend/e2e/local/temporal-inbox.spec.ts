/**
 * Crimson-Kitty PipelineInbox e2e (phase-1-plan.md step 2.6).
 *
 *   - Loads inbox with 3 mocked entries
 *   - approve / abort / retry buttons POST to the signal endpoint
 *   - Each decision is recorded in `window.__temporalSignals`
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'
import { mockTemporalAPIs, mockTemporalInboxItems } from '../fixtures/temporal-mocks'

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
    await firstRow.getByTestId('temporal-inbox-approve').click()

    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (
              (
                window as unknown as {
                  __temporalSignals?: { workflowId: string; decision: string }[]
                }
              ).__temporalSignals || []
            ).slice(-1)[0]
        )
      )
      .toMatchObject({ workflowId: expectedWorkflow, decision: 'approve' })
  })

  test('abort sends abort signal for the second row', async ({ page }) => {
    const row = page.getByTestId('temporal-inbox-row').nth(1)
    const expectedWorkflow = mockTemporalInboxItems[1].workflow_id
    await row.getByTestId('temporal-inbox-abort').click()

    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (
              (
                window as unknown as {
                  __temporalSignals?: { workflowId: string; decision: string }[]
                }
              ).__temporalSignals || []
            ).slice(-1)[0]
        )
      )
      .toMatchObject({ workflowId: expectedWorkflow, decision: 'abort' })
  })

  test('retry sends retry signal for the third row', async ({ page }) => {
    const row = page.getByTestId('temporal-inbox-row').nth(2)
    const expectedWorkflow = mockTemporalInboxItems[2].workflow_id
    await row.getByTestId('temporal-inbox-retry').click()

    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (
              (
                window as unknown as {
                  __temporalSignals?: { workflowId: string; decision: string }[]
                }
              ).__temporalSignals || []
            ).slice(-1)[0]
        )
      )
      .toMatchObject({ workflowId: expectedWorkflow, decision: 'retry' })
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

    await signoffRow.getByTestId('temporal-inbox-approve').click()

    await expect
      .poll(async () =>
        page.evaluate(
          () =>
            (
              (
                window as unknown as {
                  __temporalSignals?: { workflowId: string; decision: string }[]
                }
              ).__temporalSignals || []
            ).slice(-1)[0]
        )
      )
      .toMatchObject({ workflowId: expectedWorkflow, decision: 'approve' })
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
