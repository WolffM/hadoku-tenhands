/**
 * E2E Tests for the Retrospective View
 *
 * All retro tests hit the real backend (port 5001, started by webServer in
 * playwright.config.ts) so they validate actual jade-hare data.  Mocking
 * retro endpoints would defeat the purpose — these tests exist specifically
 * to catch backend data bugs like missing upstream PRs, empty comment counts,
 * or artifacts that aren't loaded.
 *
 * Non-retro endpoints (owner, pipeline stages, etc.) are still mocked for
 * speed; they are not under test here.
 *
 * Known-stable jade-hare facts asserted below:
 *   - 3 batches: crimson-kitty (0 issues, newest), jade-hare (55), dusty-lizard (8)
 *   - jade-hare: 55 dispatched, 28 upstream PRs, 1 merged (data-formulator#85)
 *   - microsoft/markitdown#183  → PR #1619 (open), timing data, SA annotations, 1 human comment
 *   - puppeteer/puppeteer#5096  → PR #14791 (open), 13 human comments (wolfib, WolffM, Lightning00Blade)
 *   - microsoft/PowerToys#22315 → PR #46315 (open), upstream-pr-body.md artifact
 *   - microsoft/PowerToys#36805 → fork PR only (stage4_pr_number=6, no upstream PR)
 *   - strapi/strapi#24822       → truly dispatched (no fork PR, no upstream PR)
 */

import { test, expect, type Page } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'

// ---- Helpers ----

/** Navigate past the select screen, then click Retrospective. */
async function navigateToRetro(page: Page): Promise<void> {
  await page.goto('/?key=test-key')
  await expect(page.locator('text=VibeDispatch')).toBeVisible()
  await page
    .locator('.pipeline-select-card')
    .filter({ hasText: 'OSS Contribution Pipeline' })
    .click()
  await expect(page.locator('.nav-tabs__tab').filter({ hasText: /Retrospective/i })).toBeVisible()
  await page
    .locator('.nav-tabs__tab')
    .filter({ hasText: /Retrospective/i })
    .click()
  await expect(page.locator('.retro-view')).toBeVisible()
}

/** Click the jade-hare tab and wait for its cards to render. */
async function navigateToJadeHare(page: Page): Promise<void> {
  await navigateToRetro(page)
  await page.locator('.retro-tab').filter({ hasText: 'jade-hare' }).click()
  await expect(page.locator('.retro-tab--active').filter({ hasText: 'jade-hare' })).toBeVisible()
  // Wait for at least the first card to load
  await expect(page.locator('.retro-card').first()).toBeVisible()
}

/** Find a card by its origin slug + issue number as shown in the card header. */
function getCard(page: Page, slug: string, issueNum: number) {
  return page.locator('.retro-card').filter({
    has: page.locator(`.retro-card__repo-link:text("${slug}#${issueNum}")`)
  })
}

// ---- Navigation (structural — mockAllAPIs is fine, no retro data loaded) ----

test.describe('RetroView — Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
  })

  test('Retrospective tab is hidden on the select view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await expect(
      page.locator('.nav-tabs__tab').filter({ hasText: /Retrospective/i })
    ).not.toBeVisible()
  })

  test('Retrospective tab appears after leaving select view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await page
      .locator('.pipeline-select-card')
      .filter({ hasText: 'OSS Contribution Pipeline' })
      .click()
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: /Retrospective/i })).toBeVisible()
  })

  test('clicking Retrospective tab loads the retro view', async ({ page }) => {
    await navigateToRetro(page)
    await expect(page.locator('.retro-view')).toBeVisible()
  })
})

// ---- Batch Tabs (real backend — validates actual batch data) ----

test.describe('RetroView — Batch Tabs', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToRetro(page)
  })

  test('shows tabs for all three real batches', async ({ page }) => {
    await expect(page.locator('.retro-tab').filter({ hasText: 'crimson-kitty' })).toBeVisible()
    await expect(page.locator('.retro-tab').filter({ hasText: 'jade-hare' })).toBeVisible()
    await expect(page.locator('.retro-tab').filter({ hasText: 'dusty-lizard' })).toBeVisible()
  })

  test('crimson-kitty (newest) is active by default', async ({ page }) => {
    await expect(
      page.locator('.retro-tab--active').filter({ hasText: 'crimson-kitty' })
    ).toBeVisible()
  })

  test('jade-hare tab has merged count badge (1 merged PR)', async ({ page }) => {
    const jadeTab = page.locator('.retro-tab').filter({ hasText: 'jade-hare' })
    await expect(jadeTab.locator('.retro-tab__badge')).toHaveText('1 merged')
  })

  test('crimson-kitty default view shows empty batch message', async ({ page }) => {
    // crimson-kitty was just created, has no dispatched issues yet
    await expect(page.locator('.retro-empty')).toContainText('No issues in this batch yet')
  })

  test('clicking jade-hare makes it active', async ({ page }) => {
    await page.locator('.retro-tab').filter({ hasText: 'jade-hare' }).click()
    await expect(page.locator('.retro-tab--active').filter({ hasText: 'jade-hare' })).toBeVisible()
  })

  test('switching tabs fires API request for the new batch id', async ({ page }) => {
    const [request] = await Promise.all([
      page.waitForRequest(req => req.url().includes('/oss/retro/batch/jade-hare')),
      page.locator('.retro-tab').filter({ hasText: 'jade-hare' }).click()
    ])
    expect(request.url()).toContain('jade-hare')
  })

  test('no Older dropdown with 3 batches', async ({ page }) => {
    await expect(page.locator('.retro-tab--older')).not.toBeVisible()
  })

  test('Older dropdown shown and works when >5 batches (mocked override)', async ({ page }) => {
    const manyBatches = Array.from({ length: 7 }, (_, i) => ({
      batch_id: `batch-${i + 1}`,
      created_at: new Date(Date.now() - i * 86400000).toISOString(),
      note: '',
      issue_count: 1,
      upstream_pr_count: 0,
      upstream_merged: 0,
      upstream_closed: 0,
      upstream_open: 0,
      has_fork_pr: 0
    }))
    await page.route('**/dispatch/api/oss/retro/batches', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, batches: manyBatches, owner: 'test-user' })
      })
    })
    await page.route('**/dispatch/api/oss/retro/batch/**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          batch: manyBatches[0],
          issues: [],
          owner: 'test-user'
        })
      })
    })
    // Reload to pick up the override (retro: false means retro routes are not pre-intercepted)
    await navigateToRetro(page)

    await expect(page.locator('.retro-tab--older')).toBeVisible()
    const visibleTabs = page.locator('.retro-tab:not(.retro-tab--older)')
    await expect(visibleTabs).toHaveCount(5)

    await page.locator('.retro-tab--older').click()
    await expect(page.locator('.retro-tabs__dropdown')).toBeVisible()
    await expect(page.locator('.retro-tabs__dropdown-item')).toHaveCount(2)

    await page.locator('.retro-tabs__dropdown-item').first().click()
    await expect(page.locator('.retro-tabs__dropdown')).not.toBeVisible()
  })
})

// ---- BatchSummaryPanel — validates real jade-hare funnel counts ----

test.describe('RetroView — BatchSummaryPanel (jade-hare)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    await expect(page.locator('.batch-summary')).toBeVisible()
  })

  test('shows jade-hare as the active batch id', async ({ page }) => {
    await expect(page.locator('.batch-summary__id')).toHaveText('jade-hare')
  })

  test('funnel shows 55 dispatched issues', async ({ page }) => {
    await expect(
      page
        .locator('.batch-summary__stage')
        .filter({ hasText: 'Dispatched' })
        .locator('.batch-summary__count')
    ).toHaveText('55')
  })

  test('funnel shows 28 upstream PRs submitted', async ({ page }) => {
    await expect(
      page
        .locator('.batch-summary__stage')
        .filter({ hasText: 'Upstream PRs' })
        .locator('.batch-summary__count')
    ).toHaveText('28')
  })

  test('outcome shows 1 merged PR (data-formulator#85)', async ({ page }) => {
    await expect(
      page.locator('.batch-summary__outcome--success').locator('.batch-summary__count')
    ).toHaveText('1')
  })

  test('outcome shows 17 closed PRs', async ({ page }) => {
    await expect(
      page.locator('.batch-summary__outcome--closed').locator('.batch-summary__count')
    ).toHaveText('17')
  })

  test('outcome shows 10 open PRs', async ({ page }) => {
    await expect(
      page.locator('.batch-summary__outcome--open').locator('.batch-summary__count')
    ).toHaveText('10')
  })
})

// ---- IssueRetroCard header — validates real markitdown#183 data ----

test.describe('RetroView — IssueRetroCard header (markitdown#183)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
  })

  test('shows repo#issue link in header', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-card__repo-link')).toHaveText('microsoft/markitdown#183')
    await expect(card.locator('.retro-card__repo-link')).toHaveAttribute(
      'href',
      'https://github.com/microsoft/markitdown/issues/183'
    )
  })

  test('shows upstream PR link (PR #1619)', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-card__pr-link')).toBeVisible()
    await expect(card.locator('.retro-card__pr-link')).toHaveText('PR #1619')
    await expect(card.locator('.retro-card__pr-link')).toHaveAttribute(
      'href',
      'https://github.com/microsoft/markitdown/pull/1619'
    )
  })

  test('shows Open upstream stage badge', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-badge--open')).toContainText('Open upstream')
  })

  test('shows context tier badge', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-badge--neutral')).toContainText('tier 1')
  })

  test('shows 1 human comment badge', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-badge--comments')).toContainText('1 human comment')
  })

  test('puppeteer/puppeteer#5096 shows 13 human comments badge', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await expect(card.locator('.retro-badge--comments')).toContainText('13 human comments')
  })

  test('PowerToys#36805 shows Fork PR created badge (no upstream PR)', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 36805)
    await expect(card.locator('.retro-badge--neutral').first()).toContainText('Fork PR created')
    await expect(card.locator('.retro-card__pr-link')).not.toBeVisible()
  })

  test('strapi#24822 shows Dispatched badge (never got a fork PR)', async ({ page }) => {
    const card = getCard(page, 'strapi/strapi', 24822)
    await expect(card.locator('.retro-badge--neutral').first()).toContainText('Dispatched')
    await expect(card.locator('.retro-card__pr-link')).not.toBeVisible()
  })

  test('data-formulator#85 shows Merged upstream badge', async ({ page }) => {
    const card = getCard(page, 'microsoft/data-formulator', 85)
    await expect(card.locator('.retro-badge--success')).toContainText('Merged upstream')
  })
})

// ---- Card expand / collapse (behavioral) ----

test.describe('RetroView — Card expand/collapse', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
  })

  test('card body is hidden by default', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-card__body')).not.toBeVisible()
  })

  test('clicking header expands the card', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await card.locator('.retro-card__header').click()
    await expect(card.locator('.retro-card__body')).toBeVisible()
  })

  test('clicking header again collapses the card', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await card.locator('.retro-card__header').click()
    await expect(card.locator('.retro-card__body')).toBeVisible()
    await card.locator('.retro-card__header').click()
    await expect(card.locator('.retro-card__body')).not.toBeVisible()
  })

  test('cards expand independently', async ({ page }) => {
    const markitdownCard = getCard(page, 'microsoft/markitdown', 183)
    const powerToysCard = getCard(page, 'microsoft/PowerToys', 22315)
    await markitdownCard.locator('.retro-card__header').click()
    await expect(markitdownCard.locator('.retro-card__body')).toBeVisible()
    await expect(powerToysCard.locator('.retro-card__body')).not.toBeVisible()
  })
})

// ---- Human comments — validates real puppeteer#5096 upstream review thread ----

test.describe('RetroView — Human comments (puppeteer#5096)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await card.locator('.retro-card__header').click()
    await expect(card.locator('.retro-card__body')).toBeVisible()
  })

  test('human comments section is open by default when card expands', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await expect(card.locator('.comment-thread').first()).toBeVisible()
  })

  test('wolfib maintainer comment is visible', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await expect(
      card.locator('.comment__author').filter({ hasText: '@wolfib' }).first()
    ).toBeVisible()
    await expect(
      card.locator('.comment__body').filter({ hasText: /What is this trying to achieve/i })
    ).toBeVisible()
  })

  test('Lightning00Blade inline comment is visible', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await expect(
      card.locator('.comment__author').filter({ hasText: '@Lightning00Blade' }).first()
    ).toBeVisible()
  })

  test('bot comments are filtered out — no copilot-swe-agent shown', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await expect(
      card.locator('.comment__author').filter({ hasText: '@copilot-swe-agent' })
    ).not.toBeVisible()
  })

  test('Upstream PR thread label is shown', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    await expect(
      card.locator('.comment-thread__label').filter({ hasText: 'Upstream PR' })
    ).toBeVisible()
  })

  test('inline comment shows path and line number', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    // Lightning00Blade first inline comment is at line 399
    await expect(card.locator('.comment--inline').first()).toBeVisible()
    await expect(card.locator('.comment__location').first()).toBeVisible()
  })
})

// ---- Timeline — validates real markitdown#183 timing data ----

test.describe('RetroView — Timeline (markitdown#183)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    const card = getCard(page, 'microsoft/markitdown', 183)
    await card.locator('.retro-card__header').click()
    await card
      .locator('.retro-section__toggle')
      .filter({ hasText: /Timeline/i })
      .click()
    await expect(card.locator('.retro-timeline')).toBeVisible()
  })

  test('shows Dispatched step', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(
      card.locator('.retro-timeline__label').filter({ hasText: 'Dispatched' })
    ).toBeVisible()
  })

  test('shows Upstream submitted step', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(
      card.locator('.retro-timeline__label').filter({ hasText: 'Upstream submitted' })
    ).toBeVisible()
  })

  test('shows 6 timeline steps', async ({ page }) => {
    // Dispatched, Fork PR created, SA run, Review, Remediation, Upstream submitted
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-timeline__step')).toHaveCount(6)
  })

  test('all timestamps are non-empty', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    const timestamps = card.locator('.retro-timeline__ts')
    const count = await timestamps.count()
    for (let i = 0; i < count; i++) {
      await expect(timestamps.nth(i)).not.toBeEmpty()
    }
  })

  test('shows delta between consecutive steps', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-timeline__delta').first()).toBeVisible()
  })

  test('data-formulator#85 timeline has Merged success step', async ({ page }) => {
    const card = getCard(page, 'microsoft/data-formulator', 85)
    await card.locator('.retro-card__header').click()
    await card
      .locator('.retro-section__toggle')
      .filter({ hasText: /Timeline/i })
      .click()
    await expect(card.locator('.retro-timeline__step--success')).toBeVisible()
    await expect(
      card.locator('.retro-timeline__step--success .retro-timeline__label')
    ).toContainText('Merged')
  })
})

// ---- Workflow chips — validates real markitdown#183 workflow data ----

test.describe('RetroView — Copilot workflow chips (markitdown#183)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    const card = getCard(page, 'microsoft/markitdown', 183)
    await card.locator('.retro-card__header').click()
    await card
      .locator('.retro-section__toggle')
      .filter({ hasText: /Copilot workflow/i })
      .click()
  })

  test('code review chip shows yes', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(
      card.locator('.workflow-chip--yes').filter({ hasText: /Code review/i })
    ).toBeVisible()
  })

  test('reproduced chip shows no (agent did not reproduce the bug)', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(
      card.locator('.workflow-chip--no').filter({ hasText: /Reproduced/i })
    ).toBeVisible()
  })

  test('step count is shown (26 steps for markitdown#183)', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.workflow-metrics__meta')).toContainText('26 steps')
  })
})

// ---- SA findings — validates real markitdown#183 static analysis annotations ----

test.describe('RetroView — SA findings (markitdown#183)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    const card = getCard(page, 'microsoft/markitdown', 183)
    await card.locator('.retro-card__header').click()
    await card
      .locator('.retro-section__toggle')
      .filter({ hasText: /SA findings/i })
      .click()
  })

  test('SA findings section is present', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.sa-finding')).toBeVisible()
  })

  test('finding shows the annotated file path', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.sa-finding__loc')).toContainText('latex_dict.py')
  })

  test('finding shows the lint message', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.sa-finding__msg')).toContainText('F601')
  })
})

// ---- ContextPanel — validates real PowerToys#22315 upstream PR body artifact ----

test.describe('RetroView — ContextPanel (PowerToys#22315)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await card.locator('.retro-card__header').click()
    await card
      .locator('.retro-section__toggle')
      .filter({ hasText: /Artifacts/i })
      .click()
  })

  test('upstream PR body artifact link is shown', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await expect(
      card.locator('.retro-artifact-link').filter({ hasText: /Upstream PR body/i })
    ).toBeVisible()
  })

  test('context brief is unavailable for this issue (no context.md captured)', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await expect(
      card.locator('.retro-artifact-missing').filter({ hasText: /Context brief unavailable/i })
    ).toBeVisible()
  })

  test('clicking upstream PR body opens ContextPanel', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await card
      .locator('.retro-artifact-link')
      .filter({ hasText: /Upstream PR body/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await expect(page.locator('.context-panel__title')).toContainText('Upstream PR body')
  })

  test('ContextPanel shows the PR body content', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await card
      .locator('.retro-artifact-link')
      .filter({ hasText: /Upstream PR body/i })
      .click()
    await expect(page.locator('.context-panel__body')).toContainText('Fix 22315')
  })

  test('close button dismisses ContextPanel', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await card
      .locator('.retro-artifact-link')
      .filter({ hasText: /Upstream PR body/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await page.locator('.context-panel__close').click()
    await expect(page.locator('.context-panel')).not.toBeVisible()
  })

  test('Escape key dismisses ContextPanel', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await card
      .locator('.retro-artifact-link')
      .filter({ hasText: /Upstream PR body/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('.context-panel')).not.toBeVisible()
  })

  test('clicking overlay backdrop dismisses ContextPanel', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await card
      .locator('.retro-artifact-link')
      .filter({ hasText: /Upstream PR body/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await page.locator('.context-panel-overlay').click()
    await expect(page.locator('.context-panel')).not.toBeVisible()
  })
})

// ---- Pre-telemetry placeholder — strapi#24822 was dispatched but never got further ----

test.describe('RetroView — Pre-telemetry state (strapi#24822)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    await navigateToJadeHare(page)
    const card = getCard(page, 'strapi/strapi', 24822)
    await card.locator('.retro-card__header').click()
    await expect(card.locator('.retro-card__body')).toBeVisible()
  })

  test('pre-telemetry placeholder is shown when no retro data exists', async ({ page }) => {
    const card = getCard(page, 'strapi/strapi', 24822)
    await expect(card.locator('.retro-placeholder')).toBeVisible()
    await expect(card.locator('.retro-placeholder')).toContainText('before full telemetry')
  })

  test('human comments section shows unavailable message (no data captured)', async ({ page }) => {
    const card = getCard(page, 'strapi/strapi', 24822)
    await expect(
      card.locator('.retro-empty-section').filter({ hasText: 'Comment data unavailable' })
    ).toBeVisible()
  })

  test('no Copilot workflow section rendered (no workflow captured)', async ({ page }) => {
    const card = getCard(page, 'strapi/strapi', 24822)
    await expect(
      card.locator('.retro-section__toggle').filter({ hasText: /Copilot workflow/i })
    ).not.toBeVisible()
  })

  test('artifacts section shows both artifacts as missing', async ({ page }) => {
    const card = getCard(page, 'strapi/strapi', 24822)
    await card
      .locator('.retro-section__toggle')
      .filter({ hasText: /Artifacts/i })
      .click()
    await expect(card.locator('.retro-artifact-missing')).toHaveCount(2)
  })
})
