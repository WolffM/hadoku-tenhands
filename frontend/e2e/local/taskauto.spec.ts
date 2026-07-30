/**
 * Task Automation view e2e.
 *
 * Two behaviours worth pinning down:
 *
 *   - A merged PR's row leaves on the merge. The backend keeps listing it
 *     until it re-reads GitHub, and the naive "clear the spinner, then
 *     reload" order made the row flash back to a live Merge button in that
 *     window — a button that would merge an already-merged PR.
 *   - A lane card opens the task behind it. Lane cards truncate, so the card
 *     is a pointer to the task rather than the task itself.
 */

import { test, expect } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'
import { mockTaskAutoAPIs, mockTaskAutoStatus } from '../fixtures/taskauto-mocks'

test.describe('Task automation', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await mockTaskAutoAPIs(page)
    await page.goto('/?key=test-key')
    await page.locator('.pipeline-select-card').filter({ hasText: 'Task Automation' }).click()
  })

  test('merging removes the row even while status still lists the PR', async ({ page }) => {
    const prs = page.getByTestId('taskauto-prs')
    await expect(prs.locator('.taskauto-pr')).toHaveCount(2)

    await page.getByTestId('taskauto-pr-72').getByRole('button', { name: 'Merge' }).click()

    // Gone, and it stays gone: the mocked status keeps returning PR 72.
    await expect(page.getByTestId('taskauto-pr-72')).toHaveCount(0)
    await expect(prs.locator('.taskauto-pr')).toHaveCount(1)
    await page.getByRole('button', { name: 'Refresh' }).click()
    await expect(page.getByTestId('taskauto-pr-72')).toHaveCount(0)

    // The other PR is untouched and still mergeable.
    await expect(
      page.getByTestId('taskauto-pr-73').getByRole('button', { name: 'Merge' })
    ).toBeEnabled()

    const merges = await page.evaluate(() => window.__taskautoMerges ?? [])
    expect(merges).toHaveLength(1)
    // `auto: false` matters: the plain Merge button merges now. "Merge when
    // green" is the other button, and it leaves the PR open for CI to veto.
    expect(merges[0]).toMatchObject({ repo: 'WolffM/hadoku-task', number: 72, auto: false })
  })

  test('the Review tab count drops with the merged row', async ({ page }) => {
    await expect(page.getByTestId('taskauto-tab-review')).toContainText('2')
    await page.getByTestId('taskauto-pr-72').getByRole('button', { name: 'Merge' }).click()
    await expect(page.getByTestId('taskauto-tab-review')).toContainText('1')
  })

  test('a lane card opens the task with its timeline, PR and plan', async ({ page }) => {
    await page.getByTestId('taskauto-tab-boards').click()

    const taskId = mockTaskAutoStatus.boards[0].lanes.landed[0].id
    await page.getByTestId(`taskauto-task-${taskId}`).click()

    const modal = page.getByTestId('taskauto-task-modal')
    await expect(modal).toBeVisible()
    await expect(modal.locator('.modal__title')).toContainText('dragging while in edit boards view')
    // Claim log oldest first, then the PR it produced.
    await expect(modal.locator('.taskauto-timeline__item')).toHaveCount(3)
    await expect(modal.locator('.taskauto-timeline__item').nth(1)).toContainText('planned — ready')
    await expect(modal.locator('.taskauto-detail__pr')).toContainText('#72')
    await expect(modal.locator('.taskauto-detail__notes')).toContainText('fix the drag handler')

    await page.keyboard.press('Escape')
    await expect(modal).toHaveCount(0)
  })
})
