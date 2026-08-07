/**
 * Crimson-Kitty (Temporal) — the evidence-gated pipeline surface.
 *
 * The behaviour worth protecting is the operator inbox's confirm step: a
 * decision is a two-stage action (choose, then confirm with a reason) because
 * the reason code feeds the calibration corpus. The suite this replaced still
 * asserted the one-click version and had been red ever since the confirm step
 * landed.
 */

import { test, expect } from '../fixtures/base'
import { mockTemporalInboxItems } from '../fixtures/data'

/** The signoff item renders a different card; the rest share the standard row. */
const SIGNOFF = mockTemporalInboxItems.find(i => i.gate === 'operator_signoff')!
const STANDARD = mockTemporalInboxItems.filter(i => i.gate !== 'operator_signoff')

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await page.getByRole('heading', { name: 'Crimson-Kitty (Temporal)' }).click()
  await expect(page.getByTestId('temporal-pipeline-view')).toBeVisible()
})

test.describe('shell', () => {
  test('shows the three tabs and opens on the inbox', async ({ page }) => {
    const tabs = page.getByTestId('temporal-tabs')
    await expect(tabs.locator('button')).toHaveCount(3)
    for (const key of ['inbox', 'active', 'archive']) {
      await expect(page.getByTestId(`temporal-tab-${key}`)).toBeVisible()
    }
    await expect(page.getByTestId('temporal-inbox')).toBeVisible()
  })
})

test.describe('operator inbox', () => {
  test('renders one row per queued item', async ({ page }) => {
    await expect(page.getByTestId('temporal-inbox-row')).toHaveCount(mockTemporalInboxItems.length)
  })

  test('the signoff item renders the signoff card, with its PR title and preview link', async ({
    page
  }) => {
    await expect(page.getByTestId('temporal-inbox-pr-title')).toContainText(SIGNOFF.pr_title!)
    await expect(page.getByTestId('temporal-inbox-preview-link')).toHaveAttribute(
      'href',
      SIGNOFF.operator_pr_url!
    )
  })

  test('choosing a decision sends nothing until it is confirmed', async ({ page, api }) => {
    const row = page.getByTestId('temporal-inbox-row').first()
    await row.getByTestId('temporal-inbox-approve').click()

    await expect(page.getByTestId('temporal-inbox-reason-picker')).toBeVisible()
    expect(api.posts.filter(p => p.key.startsWith('POST /api/temporal/issue'))).toEqual([])
  })

  test('cancelling the reason picker sends nothing and closes it', async ({ page, api }) => {
    const row = page.getByTestId('temporal-inbox-row').first()
    await row.getByTestId('temporal-inbox-approve').click()
    await page.getByTestId('temporal-inbox-reason-cancel').click()

    await expect(page.getByTestId('temporal-inbox-reason-picker')).toBeHidden()
    expect(api.posts.filter(p => p.key.startsWith('POST /api/temporal/issue'))).toEqual([])
  })

  test('confirming sends the decision, and the chosen reason travels with it', async ({
    page,
    api
  }) => {
    const row = page.getByTestId('temporal-inbox-row').first()
    await row.getByTestId('temporal-inbox-approve').click()

    await page.getByTestId('temporal-inbox-reason-text').fill('looks right to me')
    await page.getByTestId('temporal-inbox-reason-confirm').click()

    await expect
      .poll(() => api.posts.filter(p => p.key.startsWith('POST /api/temporal/issue')).length)
      .toBe(1)

    const signal = api.posts.find(p => p.key.startsWith('POST /api/temporal/issue'))!
    expect(signal.key).toContain('/signal')
    expect(signal.body).toMatchObject({
      decision: 'approve',
      reason_text: 'looks right to me'
    })
    // A reason CODE is always sent, even when the operator types nothing —
    // it is the field the calibration corpus is keyed on.
    expect(signal.body?.reason_code).toBeTruthy()
  })

  test('abort is offered on the standard rows alongside approve', async ({ page }) => {
    // Both decisions exist; the signoff card and the judge-defer rows differ in
    // which extras they add, so this asserts the floor rather than the exact set.
    expect(STANDARD.length).toBeGreaterThan(0)
    await expect(page.getByTestId('temporal-inbox-approve').first()).toBeVisible()
    await expect(page.getByTestId('temporal-inbox-abort').first()).toBeVisible()
  })
})

test.describe('failure surfaces', () => {
  test.use({
    apiOverrides: {
      'GET /api/temporal/inbox': { success: false, error: 'temporal unreachable' }
    }
  })

  test('a failed inbox load shows the error rather than an empty queue', async ({ page }) => {
    await expect(page.getByTestId('temporal-inbox-error')).toBeVisible()
  })
})

test.describe('empty inbox', () => {
  test.use({
    apiOverrides: {
      'GET /api/temporal/inbox': { success: true, items: [], count: 0 }
    }
  })

  test('says so instead of rendering nothing', async ({ page }) => {
    await expect(page.getByTestId('temporal-inbox-empty')).toBeVisible()
    await expect(page.getByTestId('temporal-inbox-row')).toHaveCount(0)
  })
})
