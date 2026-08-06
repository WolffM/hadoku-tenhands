/**
 * Task Automation view — the board-driven pipeline surface.
 *
 * Two tabs (Review, Boards), a PR list you merge from, and a task modal.
 */

import { test, expect } from '../fixtures/base'
import { mockTaskAutoPRs, mockTaskAutoStatus } from '../fixtures/data'

const BOARD = mockTaskAutoStatus.boards[0]

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await page.getByRole('heading', { name: 'Task Automation' }).click()
  await expect(page.getByTestId('taskauto-view')).toBeVisible()
})

test.describe('tabs', () => {
  test('opens on Review and shows both tabs with their counts', async ({ page }) => {
    const tabs = page.getByTestId('taskauto-tabs')
    await expect(tabs.locator('.stage-tab')).toHaveCount(2)

    // Review counts PRs, Boards counts boards.
    await expect(page.getByTestId('taskauto-tab-review')).toContainText('Review')
    await expect(page.getByTestId('taskauto-tab-review')).toContainText(
      String(mockTaskAutoPRs.length)
    )
    await expect(page.getByTestId('taskauto-tab-boards')).toContainText(
      String(mockTaskAutoStatus.boards.length)
    )

    await expect(page.getByTestId('taskauto-tab-review')).toHaveClass(/stage-tab--active/)
  })

  test('Boards tab shows the board and its lanes', async ({ page }) => {
    await page.getByTestId('taskauto-tab-boards').click()

    const board = page.getByTestId(`taskauto-board-${BOARD.handle}`)
    await expect(board).toBeVisible()
    await expect(board.getByRole('heading', { name: BOARD.name })).toBeVisible()

    // Only lanes with tasks render a card; the fixture has one in each of two.
    for (const lane of Object.values(BOARD.lanes)) {
      for (const task of lane) {
        await expect(page.getByTestId(`taskauto-task-${task.id}`)).toBeVisible()
      }
    }
  })
})

test.describe('review queue', () => {
  test('lists every open PR the boards report', async ({ page }) => {
    const list = page.getByTestId('taskauto-prs')
    await expect(list).toBeVisible()

    for (const pr of mockTaskAutoPRs) {
      const row = page.getByTestId(`taskauto-pr-${pr.number}`)
      await expect(row).toBeVisible()
      await expect(row).toContainText(pr.title)
    }
  })

  test('merging removes the row immediately, without waiting for a reload', async ({
    page,
    api
  }) => {
    // The backend keeps returning a merged PR until it re-reads GitHub, so the
    // view filters on `mergedIds` locally. That is the behaviour under test:
    // /api/taskauto/status still reports both PRs after the merge.
    const target = mockTaskAutoPRs[0]
    const row = page.getByTestId(`taskauto-pr-${target.number}`)
    await expect(row).toBeVisible()

    await row.getByRole('button', { name: /merge/i }).click()

    await expect(row).toBeHidden()
    await expect(page.getByTestId(`taskauto-pr-${mockTaskAutoPRs[1].number}`)).toBeVisible()

    const merge = api.posts.find(p => p.key === 'POST /api/taskauto/merge')
    expect(merge?.body).toMatchObject({ repo: target.repo, number: target.number })
  })

  test('the Review tab count drops with the merged row', async ({ page }) => {
    await expect(page.getByTestId('taskauto-tab-review')).toContainText(
      String(mockTaskAutoPRs.length)
    )

    await page
      .getByTestId(`taskauto-pr-${mockTaskAutoPRs[0].number}`)
      .getByRole('button', { name: /merge/i })
      .click()

    await expect(page.getByTestId('taskauto-tab-review')).toContainText(
      String(mockTaskAutoPRs.length - 1)
    )
  })
})

test.describe('task detail', () => {
  test('a lane card opens the task modal headed with its title', async ({ page }) => {
    await page.getByTestId('taskauto-tab-boards').click()

    const task = BOARD.lanes['plan-review'][0]
    await page.getByTestId(`taskauto-task-${task.id}`).click()

    const modal = page.getByTestId('taskauto-task-modal')
    await expect(modal).toBeVisible()
    await expect(modal).toContainText(task.title)
  })
})

test.describe('failure surfaces', () => {
  test.use({
    apiOverrides: {
      'GET /api/taskauto/status': { success: false, error: 'board unreachable' }
    }
  })

  test('a failed status load shows the error instead of an empty board', async ({ page }) => {
    await expect(page.getByTestId('taskauto-error')).toBeVisible()
  })
})
