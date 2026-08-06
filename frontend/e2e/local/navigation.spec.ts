/**
 * The app shell: three top tabs, four pipeline cards, and getting in and out of
 * each pipeline.
 *
 * Navigation.tsx is explicit that pipelines are NOT top-level tabs — you pick
 * one from Home and click Home to switch. The suite this replaced asserted
 * three pipeline tiles; there have been four since Task Automation landed, and
 * nothing caught it because `pnpm test` was passing a project name that did not
 * exist and never ran. Counts are asserted exactly here so the next addition
 * fails loudly rather than silently.
 */

import { test, expect } from '../fixtures/base'

const TOP_TABS = ['Home', 'Retrospective', 'Health']

const PIPELINES = [
  { title: 'Vibecheck Pipeline', marker: 'Install VibeCheck' },
  { title: 'OSS Contribution Pipeline', marker: 'Repo Health' },
  { title: 'Crimson-Kitty (Temporal)', marker: 'Eligible' },
  { title: 'Task Automation', marker: 'Inbox' }
]

test.beforeEach(async ({ page }) => {
  await page.goto('/')
})

test.describe('shell', () => {
  test('renders exactly the three top tabs', async ({ page }) => {
    const tabs = page.locator('.nav-tabs__tab')
    await expect(tabs).toHaveCount(TOP_TABS.length)
    await expect(tabs).toHaveText(TOP_TABS)
  })

  test('opens on the pipeline picker with Home active', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Select a Pipeline' })).toBeVisible()
    await expect(page.locator('.nav-tabs__tab--active')).toHaveText('Home')
  })

  test('offers exactly the four pipelines, each with its stage list', async ({ page }) => {
    const cards = page.locator('.pipeline-select-card__title')
    await expect(cards).toHaveCount(PIPELINES.length)
    await expect(cards).toHaveText(PIPELINES.map(p => p.title))

    for (const { marker } of PIPELINES) {
      await expect(page.getByText(marker, { exact: true }).first()).toBeVisible()
    }
  })
})

test.describe('entering and leaving a pipeline', () => {
  for (const { title } of PIPELINES) {
    test(`${title} opens from Home and Home comes back`, async ({ page }) => {
      await page.getByRole('heading', { name: title }).click()

      // The picker is gone — we are inside the pipeline.
      await expect(page.getByRole('heading', { name: 'Select a Pipeline' })).toBeHidden()

      await page.getByRole('button', { name: 'Home', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'Select a Pipeline' })).toBeVisible()
    })
  }

  test('Retrospective and Health are reachable directly from any pipeline', async ({ page }) => {
    await page.getByRole('heading', { name: 'Task Automation' }).click()

    await page.getByRole('button', { name: 'Health', exact: true }).click()
    await expect(page.locator('.nav-tabs__tab--active')).toHaveText('Health')

    await page.getByRole('button', { name: 'Retrospective', exact: true }).click()
    await expect(page.locator('.nav-tabs__tab--active')).toHaveText('Retrospective')
    await expect(page.getByTestId('retro-view')).toBeVisible()
  })
})
