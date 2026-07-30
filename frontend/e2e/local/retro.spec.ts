/**
 * E2E Tests for the Retrospective View
 *
 * All retro tests hit the real backend (started by webServer in
 * playwright.config.ts) so they validate actual jade-hare data.  Mocking
 * retro endpoints would defeat the purpose — these tests exist specifically
 * to catch backend data bugs like missing upstream PRs, empty comment counts,
 * or artifacts that aren't loaded.
 *
 * Non-retro endpoints (owner, pipeline stages, etc.) are still mocked for
 * speed; they are not under test here.
 *
 * Known-stable jade-hare facts asserted below. "Stable" means it cannot move
 * without a data bug — PR *states* keep drifting as upstream maintainers act,
 * so those are asserted against the API rather than pinned to a number:
 *   - 3 batches: crimson-kitty (0 issues, newest), jade-hare (55), dusty-lizard (8)
 *   - jade-hare: 55 dispatched, ≥28 upstream PRs, ≥1 merged (data-formulator#85)
 *   - microsoft/markitdown#183  → PR #1619 open (plus a later fork-only row
 *     that must not shadow it), timing data, SA annotations, human comments
 *   - puppeteer/puppeteer#5096  → ≥13 human comments (wolfib, WolffM, Lightning00Blade)
 *   - microsoft/PowerToys#22315 → two PRs; #46315 (newer, open) is the outcome,
 *     not #46124 (older, closed). Plus the upstream-pr-body.md artifact.
 *   - microsoft/PowerToys#36805 → dispatched, never reached upstream
 *   - strapi/strapi#24822       → dispatched with no retro data captured at all
 *
 * jade-hare predates both context tiers and fork-PR tracking, so those two
 * badges are covered on crimson-kitty, the batch whose records carry them.
 */

import { test, expect, type Page } from '../fixtures/base'
import { mockAllAPIs } from '../fixtures/api-mocks'

// Run retro tests serially — the Flask backend is single-threaded and the
// jade-hare batch endpoint (55 issues × session-artifact file I/O) is slow
// under heavy parallel load.  Other spec files still run concurrently.
test.describe.configure({ mode: 'serial' })

// ---- Helpers ----

/** Navigate past the select screen, then click Retrospective.
 *
 * Waits for networkidle so the default batch's content (crimson-kitty) is
 * fully loaded before tests start making assertions.
 */
async function navigateToRetro(page: Page): Promise<void> {
  await page.goto('/?key=test-key')
  await expect(page.locator('text=TenHands')).toBeVisible()
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
  // Wait for the default batch's issue list to settle — either cards or empty state
  await page
    .locator('.retro-issue-list')
    .locator('.retro-card, .retro-empty')
    .first()
    .waitFor({ state: 'attached', timeout: 25_000 })
}

/** Click the jade-hare tab and wait for all cards to render.
 *
 * jade-hare has 55 issues with session-artifact file I/O per issue, so the
 * batch detail response can be slow when many tests run in parallel.  We wait
 * for networkidle (no requests for 500 ms) before asserting on card content so
 * the full response is guaranteed to have arrived and rendered.
 */
async function navigateToJadeHare(page: Page): Promise<void> {
  await navigateToRetro(page)
  await page.locator('.retro-tab').filter({ hasText: 'jade-hare' }).click()
  await expect(page.locator('.retro-tab--active').filter({ hasText: 'jade-hare' })).toBeVisible({
    timeout: 15_000
  })
  // Wait for the jade-hare batch detail API call to fully complete
  await page.waitForResponse(
    resp => resp.url().includes('/oss/retro/batch/jade-hare') && resp.status() === 200,
    { timeout: 40_000 }
  )
  await expect(page.locator('.retro-card').first()).toBeVisible({ timeout: 15_000 })
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

  // Home / Retrospective / Health are always-visible top-level tabs since the
  // 2026-04-30 nav cleanup (see `components/common/Navigation.tsx`) — the
  // select view is not an exception to that, it is where you start.
  test('Retrospective tab is reachable from the select view', async ({ page }) => {
    await page.goto('/?key=test-key')
    await expect(page.locator('text=Select a Pipeline')).toBeVisible()
    await expect(page.locator('.nav-tabs__tab').filter({ hasText: /Retrospective/i })).toBeVisible()
  })

  test('Retrospective tab stays available inside a pipeline', async ({ page }) => {
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

  test('empty batch shows no-issues message (mocked override)', async ({ page }) => {
    // Use a mocked override so this test is not fragile to new dispatches
    await page.route('**/tenhands/api/oss/retro/batch/dusty-lizard', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          batch: {
            batch_id: 'dusty-lizard',
            created_at: '2026-02-16T00:00:00Z',
            note: '',
            issues: []
          },
          issues: [],
          owner: 'WolffM'
        })
      })
    })
    await page.locator('.retro-tab').filter({ hasText: 'dusty-lizard' }).click()
    await expect(
      page.locator('.retro-tab--active').filter({ hasText: 'dusty-lizard' })
    ).toBeVisible()
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
    await page.route('**/tenhands/api/oss/retro/batches', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, batches: manyBatches, owner: 'test-user' })
      })
    })
    await page.route('**/tenhands/api/oss/retro/batch/**', async route => {
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
//
// jade-hare is finished, but its numbers are not frozen: upstream maintainers
// keep closing and merging PRs, so open/closed drift with no code change here.
// Asserting yesterday's split makes this file go red on someone else's merge
// button, which is how it sat broken. So: the batch's own history (dispatched,
// and the PRs we submitted) is asserted as a fixed floor — a submitted PR is a
// historical fact and can only be lost by a data bug, which is exactly what
// this file exists to catch — while the outcome split is checked against the
// API that feeds the panel, plus the invariants that must hold whatever the
// maintainers do.

interface BatchFunnel {
  batch_id: string
  issue_count: number
  upstream_pr_count: number
  upstream_merged: number
  upstream_closed: number
  upstream_open: number
}

/** The funnel counts for one batch, straight from the API the panel renders. */
async function funnelFromApi(page: Page, batchId: string): Promise<BatchFunnel> {
  const res = await page.request.get('/tenhands/api/oss/retro/batches', {
    headers: { 'X-User-Key': 'test-key' }
  })
  expect(res.ok()).toBe(true)
  const body = (await res.json()) as { batches: BatchFunnel[] }
  const batch = body.batches.find(b => b.batch_id === batchId)
  expect(batch, `batch ${batchId} missing from /oss/retro/batches`).toBeDefined()
  return batch!
}

function stageCount(page: Page, label: string) {
  return page
    .locator('.batch-summary__stage')
    .filter({ hasText: label })
    .locator('.batch-summary__count')
}

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
    await expect(stageCount(page, 'Dispatched')).toHaveText('55')
  })

  test('funnel shows every upstream PR the batch ever submitted', async ({ page }) => {
    const api = await funnelFromApi(page, 'jade-hare')
    // 28 were submitted by the time this batch was written up; PRs are never
    // un-submitted, so fewer than that means data went missing.
    expect(api.upstream_pr_count).toBeGreaterThanOrEqual(28)
    await expect(stageCount(page, 'Upstream PRs')).toHaveText(String(api.upstream_pr_count))
  })

  test('outcome split matches the backend and stays within the funnel', async ({ page }) => {
    const api = await funnelFromApi(page, 'jade-hare')
    // data-formulator#85 merged upstream and cannot un-merge.
    expect(api.upstream_merged).toBeGreaterThanOrEqual(1)
    expect(api.upstream_merged + api.upstream_closed + api.upstream_open).toBeLessThanOrEqual(
      api.upstream_pr_count
    )
    expect(api.upstream_pr_count).toBeLessThanOrEqual(api.issue_count)

    await expect(
      page.locator('.batch-summary__outcome--success').locator('.batch-summary__count')
    ).toHaveText(String(api.upstream_merged))
    await expect(
      page.locator('.batch-summary__outcome--closed').locator('.batch-summary__count')
    ).toHaveText(String(api.upstream_closed))
    await expect(
      page.locator('.batch-summary__outcome--open').locator('.batch-summary__count')
    ).toHaveText(String(api.upstream_open))
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

  // Which PRs exist, and what state they are in, is upstream's business and
  // changes without us. What must always hold is that a rendered PR link is a
  // real link: `microsoft/markitdown#183` is recorded `merged-in-fork-only`
  // with no PR number, and the card used to render `PR #` pointing at "" and
  // badge it "Open upstream" — a dead link claiming the opposite of the truth.
  test('every rendered PR link points at a real pull request', async ({ page }) => {
    const links = page.locator('.retro-card__pr-link')
    const count = await links.count()
    expect(count).toBeGreaterThan(0)
    for (let i = 0; i < count; i++) {
      await expect(links.nth(i)).toHaveText(/^PR #\d+$/)
      await expect(links.nth(i)).toHaveAttribute(
        'href',
        /^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+$/
      )
    }
  })

  test('data-formulator#85 links to the PR that merged upstream', async ({ page }) => {
    const card = getCard(page, 'microsoft/data-formulator', 85)
    await expect(card.locator('.retro-card__pr-link')).toHaveText('PR #253')
    await expect(card.locator('.retro-card__pr-link')).toHaveAttribute(
      'href',
      'https://github.com/microsoft/data-formulator/pull/253'
    )
  })

  // markitdown#183 has PR #1619 open upstream *and* a later fork-only
  // bookkeeping row. The card must show the pull request: picking the newest
  // record instead reported "no upstream PR" for an issue with a live one.
  test('markitdown#183 shows its open upstream PR, not the later fork-only row', async ({
    page
  }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-card__pr-link')).toHaveText('PR #1619')
    await expect(card.locator('.retro-card__pr-link')).toHaveAttribute(
      'href',
      'https://github.com/microsoft/markitdown/pull/1619'
    )
    await expect(card.locator('.retro-badge--open')).toContainText('Open upstream')
  })

  // PowerToys#22315 has two real PRs: #46124 closed, then #46315 opened six
  // days later. Records are not stored in date order, so "the last match in
  // the list" showed the closed one as the outcome.
  test('PowerToys#22315 shows the newest submission, not the older closed one', async ({
    page
  }) => {
    const card = getCard(page, 'microsoft/PowerToys', 22315)
    await expect(card.locator('.retro-card__pr-link')).toHaveText('PR #46315')
  })

  // Context tiers arrived with the dispatch-readiness work, after jade-hare
  // ran — every record in this batch is `context_tier: null`, so the badge
  // must NOT be there. The tier badge itself is covered on crimson-kitty
  // below, which is the batch that actually carries tiers.
  test('no context tier badge on a pre-tier batch', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-badge').filter({ hasText: /tier/i })).toHaveCount(0)
  })

  // Comment counts only go up — maintainers keep replying to PRs we opened a
  // year ago. Pinning the exact number makes this file red on someone else's
  // comment, so the floor is asserted instead: the badge must be there, it
  // must be a real count, and it can never drop below what was captured.
  test('shows a human comment badge', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.retro-badge--comments')).toHaveText(/\d+ human comments?$/)
  })

  test('puppeteer/puppeteer#5096 shows its human comment count', async ({ page }) => {
    const card = getCard(page, 'puppeteer/puppeteer', 5096)
    const badge = card.locator('.retro-badge--comments')
    await expect(badge).toHaveText(/\d+ human comments?$/)
    const count = Number(/(\d+) human comments?$/.exec((await badge.innerText()).trim())?.[1])
    // 13 were captured from wolfib, WolffM and Lightning00Blade.
    expect(count).toBeGreaterThanOrEqual(13)
  })

  // jade-hare predates fork-PR tracking, so none of its records carry a
  // `stage4_pr_number` — every issue that never reached upstream reads
  // "Dispatched" here. The "Fork PR created" badge is covered on
  // crimson-kitty below, the batch whose records actually have one.
  test('PowerToys#36805 shows Dispatched (no upstream PR)', async ({ page }) => {
    const card = getCard(page, 'microsoft/PowerToys', 36805)
    await expect(card.locator('.retro-badge--neutral').first()).toContainText('Dispatched')
    await expect(card.locator('.retro-card__pr-link')).toHaveCount(0)
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

// ---- Context tier badge — crimson-kitty is the batch that carries tiers ----

test.describe('RetroView — context tier badge (crimson-kitty)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page, { retro: false })
    // crimson-kitty is newest, so it is the batch the view opens on.
    await navigateToRetro(page)
  })

  test('a tiered issue shows its context tier', async ({ page }) => {
    const tierBadges = page.locator('.retro-card .retro-badge').filter({ hasText: /tier/i })
    await expect(tierBadges.first()).toBeVisible()
    await expect(tierBadges.first()).toHaveText(/^tier \d+$/)
  })

  test('an issue that only reached a fork PR says so', async ({ page }) => {
    const card = getCard(page, 'cli/cli', 13262)
    await expect(card.locator('.retro-badge--neutral').first()).toContainText('Fork PR created')
    await expect(card.locator('.retro-card__pr-link')).toHaveCount(0)
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
    await expect(card.locator('.comment__body').first()).toBeVisible()
    await expect(card.locator('.comment__body').first()).not.toBeEmpty()
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
    // Dispatched, Fork PR created, SA run, Review, Remediation, Fork PR merged
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

  // The step count is re-derived from the captured session whenever the retro
  // is rebuilt, so the exact number is not a fact about the product.
  test('agent step count is shown', async ({ page }) => {
    const card = getCard(page, 'microsoft/markitdown', 183)
    await expect(card.locator('.workflow-metrics__meta')).toContainText(/\d+ steps/)
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

  // The single `.retro-placeholder` banner was replaced in 5a8a03c (Apr 2026)
  // by per-section "unavailable" messages — the three tests below are what
  // that state looks like now. Nothing renders that class any more.
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
