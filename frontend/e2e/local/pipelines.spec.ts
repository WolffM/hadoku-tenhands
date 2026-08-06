/**
 * The two stage-tab pipelines: Vibecheck and OSS Contribution.
 *
 * Both render through `StageTabView`, so the shape is shared — a tab strip with
 * a per-stage count, and one stage's content at a time. What differs is the
 * stage list and which endpoints feed the counts, so both are driven from the
 * same table below rather than duplicated.
 */

import { test, expect, type Page } from '../fixtures/base'
import { mockStage1Repos, mockStage2Repos, mockStage3Issues, mockStage4PRs } from '../fixtures/data'

const tabs = (page: Page) => page.locator('.stage-tab')

test.describe('Vibecheck pipeline', () => {
  const STAGES = [
    { label: 'Install VibeCheck', count: mockStage1Repos.length },
    { label: 'Run VibeCheck', count: mockStage2Repos.length },
    { label: 'Assign Copilot', count: mockStage3Issues.length },
    // Stage 4 counts only PRs that are ready, so it is not simply the array
    // length — asserted as "at most the total" rather than pinned to a number
    // that would encode isPRReady's current rules into the harness.
    { label: 'Review & Merge', count: null as number | null }
  ]

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('heading', { name: 'Vibecheck Pipeline' }).click()
  })

  test('shows the four stages in order', async ({ page }) => {
    await expect(tabs(page)).toHaveCount(STAGES.length)
    for (const [i, stage] of STAGES.entries()) {
      await expect(tabs(page).nth(i)).toContainText(stage.label)
    }
  })

  test('each stage tab carries the count of what is waiting in it', async ({ page }) => {
    for (const stage of STAGES) {
      if (stage.count === null) continue
      const tab = tabs(page).filter({ hasText: stage.label })
      await expect(tab.locator('.stage-tab__count')).toHaveText(String(stage.count))
    }

    const reviewCount = await tabs(page)
      .filter({ hasText: 'Review & Merge' })
      .locator('.stage-tab__count')
      .innerText()
    expect(Number(reviewCount)).toBeLessThanOrEqual(mockStage4PRs.length)
  })

  test('clicking a stage swaps the content below the strip', async ({ page }) => {
    const content = page.locator('.stage-content')
    const first = await content.innerText()

    await tabs(page).filter({ hasText: 'Assign Copilot' }).click()
    await expect(tabs(page).filter({ hasText: 'Assign Copilot' })).toHaveClass(/stage-tab--active/)
    await expect(content).not.toHaveText(first)
  })
})

test.describe('OSS Contribution pipeline', () => {
  const STAGES = ['Repo Health', 'Fork & Assign', 'Pipeline Runs', 'Review']

  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByRole('heading', { name: 'OSS Contribution Pipeline' }).click()
  })

  test('shows the four stages in order', async ({ page }) => {
    await expect(tabs(page)).toHaveCount(STAGES.length)
    for (const [i, label] of STAGES.entries()) {
      await expect(tabs(page).nth(i)).toContainText(label)
    }
  })

  test('opens on Pipeline Runs, not on the first tab', async ({ page }) => {
    // `defaultStageId="pipeline"` — the pipeline-runs tab is the working
    // surface, so landing on Repo Health would be a regression, not a detail.
    await expect(tabs(page).filter({ hasText: 'Pipeline Runs' })).toHaveClass(/stage-tab--active/)
  })

  test('every stage is reachable and renders content', async ({ page }) => {
    for (const label of STAGES) {
      await tabs(page).filter({ hasText: label }).click()
      await expect(tabs(page).filter({ hasText: label })).toHaveClass(/stage-tab--active/)
      await expect(page.locator('.stage-content')).not.toBeEmpty()
    }
  })
})
