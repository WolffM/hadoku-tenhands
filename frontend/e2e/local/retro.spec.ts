/**
 * Retrospective view — two tabs over two different pipelines' history.
 *
 * Legacy is the OSS-recon batch retro; Temporal is the crimson-kitty one. They
 * read from different endpoints and different stores, which is the reason the
 * tab strip exists at all.
 */

import { test, expect } from '../fixtures/base'
import { mockRetroBatches, mockTemporalBatches, mockTemporalBatchDetail } from '../fixtures/data'

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Retrospective', exact: true }).click()
  await expect(page.getByTestId('retro-view')).toBeVisible()
})

test.describe('tab strip', () => {
  test('offers both tabs and opens on Legacy', async ({ page }) => {
    await expect(page.getByTestId('retro-tab-strip')).toBeVisible()
    await expect(page.getByTestId('retro-tab-legacy')).toHaveClass(/retro-view__tab--active/)
    await expect(page.getByTestId('retro-tab-content-legacy')).toBeVisible()
    await expect(page.getByTestId('retro-tab-content-temporal')).toBeHidden()
  })

  test('switching to Temporal swaps the content', async ({ page }) => {
    await page.getByTestId('retro-tab-temporal').click()
    await expect(page.getByTestId('retro-tab-content-temporal')).toBeVisible()
    await expect(page.getByTestId('retro-tab-content-legacy')).toBeHidden()
  })
})

test.describe('legacy tab', () => {
  test('lists the recon batches', async ({ page }) => {
    const content = page.getByTestId('retro-tab-content-legacy')
    for (const batch of mockRetroBatches) {
      await expect(content.getByText(batch.batch_id, { exact: false }).first()).toBeVisible()
    }
  })
})

test.describe('temporal tab', () => {
  test.beforeEach(async ({ page }) => {
    await page.getByTestId('retro-tab-temporal').click()
    await expect(page.getByTestId('retro-tab-content-temporal')).toBeVisible()
  })

  test('offers one button per batch and asks for a selection first', async ({ page }) => {
    await expect(page.getByTestId('retro-temporal-batch-button')).toHaveCount(
      mockTemporalBatches.length
    )
    await expect(page.getByTestId('retro-temporal-no-selection')).toBeVisible()
  })

  test('picking a batch loads its issues', async ({ page }) => {
    await page.getByTestId('retro-temporal-batch-button').first().click()

    await expect(page.getByTestId('retro-temporal-issues')).toBeVisible()
    await expect(page.getByTestId('retro-temporal-issue')).toHaveCount(
      mockTemporalBatchDetail.issues.length
    )
    await expect(page.getByTestId('retro-temporal-no-selection')).toBeHidden()
  })

  test.describe('when there are no batches', () => {
    test.use({
      apiOverrides: {
        'GET /api/temporal/batches': { success: true, data: { batches: [] }, _meta: {} }
      }
    })

    test('says so rather than showing an empty picker', async ({ page }) => {
      await expect(page.getByTestId('retro-temporal-empty')).toBeVisible()
      await expect(page.getByTestId('retro-temporal-batch-button')).toHaveCount(0)
    })
  })
})

// Top-level rather than nested under 'temporal tab': on the error path the view
// early-returns the error element INSTEAD of the tab-content wrapper, so the
// shared beforeEach's wait for `retro-tab-content-temporal` would never resolve.
test.describe('temporal tab when the batch list fails', () => {
  test.use({
    apiOverrides: {
      'GET /api/temporal/batches': { success: false, error: 'state root missing', _meta: {} }
    }
  })

  test('surfaces the error instead of the batch picker', async ({ page }) => {
    await page.getByTestId('retro-tab-temporal').click()
    await expect(page.getByTestId('retro-temporal-error')).toBeVisible()
    await expect(page.getByTestId('retro-temporal-batch-button')).toHaveCount(0)
  })
})
