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
})
