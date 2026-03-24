/**
 * E2E Tests for the Retrospective View
 *
 * Covers:
 *   - Navigation to the Retro tab
 *   - Batch tabs and "Older" dropdown
 *   - BatchSummaryPanel funnel counts
 *   - IssueRetroCard header, expand/collapse, sections
 *   - Bot-filtered human comments (open by default)
 *   - Copilot workflow chips
 *   - SA findings
 *   - ContextPanel slide-in (open, close, Escape, overlay)
 *   - Empty/pre-telemetry states
 */

import { test, expect, type Page } from '../fixtures/base'
import {
  mockAllAPIs,
  mockOwner,
  mockRetroBatches,
  mockRetroBatchDetail
} from '../fixtures/api-mocks'

/** Navigate past the select screen so pipeline tabs appear, then click Retrospective. */
async function navigateToRetro(page: Page): Promise<void> {
  await page.goto('/?key=test-key')
  await expect(page.locator('text=VibeDispatch')).toBeVisible()
  // Leave the select view so pipelineTabs render
  await page
    .locator('.pipeline-select-card')
    .filter({ hasText: 'OSS Contribution Pipeline' })
    .click()
  await expect(page.locator('.nav-tabs__tab').filter({ hasText: /Retrospective/i })).toBeVisible()
  await page
    .locator('.nav-tabs__tab')
    .filter({ hasText: /Retrospective/i })
    .click()
}

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

test.describe('RetroView — Batch Tabs', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
  })

  test('shows batch tabs for each batch', async ({ page }) => {
    await expect(page.locator('.retro-tab').filter({ hasText: 'crimson-kitty' })).toBeVisible()
    await expect(page.locator('.retro-tab').filter({ hasText: 'jade-hare' })).toBeVisible()
  })

  test('first batch tab is active by default', async ({ page }) => {
    // crimson-kitty is sorted newest-first so it should be active
    await expect(
      page.locator('.retro-tab--active').filter({ hasText: 'crimson-kitty' })
    ).toBeVisible()
  })

  test('merged count badge shows on tab', async ({ page }) => {
    // crimson-kitty has upstream_merged: 1
    await expect(
      page.locator('.retro-tab').filter({ hasText: 'crimson-kitty' }).locator('.retro-tab__badge')
    ).toBeVisible()
    await expect(
      page.locator('.retro-tab').filter({ hasText: 'crimson-kitty' }).locator('.retro-tab__badge')
    ).toHaveText('1 merged')
  })

  test('clicking a different tab makes it active', async ({ page }) => {
    await page.locator('.retro-tab').filter({ hasText: 'jade-hare' }).click()
    await expect(page.locator('.retro-tab--active').filter({ hasText: 'jade-hare' })).toBeVisible()
  })

  test('Older dropdown not shown when ≤5 batches', async ({ page }) => {
    await expect(page.locator('.retro-tab--older')).not.toBeVisible()
  })

  test('Older dropdown shown and works when >5 batches', async ({ page }) => {
    // Override the batches mock with 7 batches
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
        body: JSON.stringify({ success: true, batches: manyBatches, owner: mockOwner })
      })
    })
    // Reload to pick up new mock
    await navigateToRetro(page)

    await expect(page.locator('.retro-tab--older')).toBeVisible()
    // 5 visible tabs + 1 Older button
    const visibleTabs = page.locator('.retro-tab:not(.retro-tab--older)')
    await expect(visibleTabs).toHaveCount(5)

    // Open dropdown
    await page.locator('.retro-tab--older').click()
    await expect(page.locator('.retro-tabs__dropdown')).toBeVisible()
    await expect(page.locator('.retro-tabs__dropdown-item')).toHaveCount(2)

    // Click an older batch
    await page.locator('.retro-tabs__dropdown-item').first().click()
    await expect(page.locator('.retro-tabs__dropdown')).not.toBeVisible()
  })
})

test.describe('RetroView — BatchSummaryPanel', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await expect(page.locator('.batch-summary')).toBeVisible()
  })

  test('shows batch id and note', async ({ page }) => {
    await expect(page.locator('.batch-summary__id')).toHaveText('crimson-kitty')
    await expect(page.locator('.batch-summary__note')).toContainText('Active batch')
  })

  test('funnel shows dispatched count', async ({ page }) => {
    // issue_count: 2
    await expect(
      page
        .locator('.batch-summary__stage')
        .filter({ hasText: 'Dispatched' })
        .locator('.batch-summary__count')
    ).toHaveText('2')
  })

  test('funnel shows upstream PR count', async ({ page }) => {
    // upstream_pr_count: 1
    await expect(
      page
        .locator('.batch-summary__stage')
        .filter({ hasText: 'Upstream PRs' })
        .locator('.batch-summary__count')
    ).toHaveText('1')
  })

  test('outcome shows merged count', async ({ page }) => {
    // upstream_merged: 1
    await expect(
      page.locator('.batch-summary__outcome--success').locator('.batch-summary__count')
    ).toHaveText('1')
  })
})

test.describe('RetroView — IssueRetroCard header', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await expect(page.locator('.retro-card').first()).toBeVisible()
  })

  test('shows repo#issue link in header', async ({ page }) => {
    const firstCard = page.locator('.retro-card').first()
    await expect(firstCard.locator('.retro-card__repo-link')).toHaveText('fastify/fastify#1234')
    await expect(firstCard.locator('.retro-card__repo-link')).toHaveAttribute(
      'href',
      'https://github.com/fastify/fastify/issues/1234'
    )
  })

  test('shows upstream PR link when present', async ({ page }) => {
    const firstCard = page.locator('.retro-card').first()
    await expect(firstCard.locator('.retro-card__pr-link')).toBeVisible()
    await expect(firstCard.locator('.retro-card__pr-link')).toHaveText('PR #9876')
    await expect(firstCard.locator('.retro-card__pr-link')).toHaveAttribute(
      'href',
      'https://github.com/fastify/fastify/pull/9876'
    )
  })

  test('shows stage badge — merged', async ({ page }) => {
    const firstCard = page.locator('.retro-card').first()
    await expect(firstCard.locator('.retro-badge--success')).toContainText('Merged upstream')
  })

  test('shows context tier badge', async ({ page }) => {
    const firstCard = page.locator('.retro-card').first()
    await expect(firstCard.locator('.retro-badge--neutral')).toContainText('tier 1')
  })

  test('shows human comments badge with count', async ({ page }) => {
    // First card: 2 human fork comments (copilot-swe-agent filtered out) + 1 inline
    //   + 1 upstream maintainer (github-actions[bot] filtered out) = 4 human comments
    const firstCard = page.locator('.retro-card').first()
    await expect(firstCard.locator('.retro-badge--comments')).toContainText('human comment')
  })

  test('no upstream PR link when no upstream PR', async ({ page }) => {
    // Second card: vercel/next.js#9999 has no upstream_pr
    const secondCard = page.locator('.retro-card').nth(1)
    await expect(secondCard.locator('.retro-card__pr-link')).not.toBeVisible()
  })

  test('dispatched stage badge when no PR', async ({ page }) => {
    const secondCard = page.locator('.retro-card').nth(1)
    await expect(secondCard.locator('.retro-badge--neutral').first()).toContainText('Dispatched')
  })
})

test.describe('RetroView — Card expand/collapse', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
  })

  test('card body is hidden by default', async ({ page }) => {
    await expect(page.locator('.retro-card').first().locator('.retro-card__body')).not.toBeVisible()
  })

  test('clicking header expands the card', async ({ page }) => {
    await page.locator('.retro-card__header').first().click()
    await expect(page.locator('.retro-card').first().locator('.retro-card__body')).toBeVisible()
  })

  test('clicking header again collapses the card', async ({ page }) => {
    await page.locator('.retro-card__header').first().click()
    await expect(page.locator('.retro-card__body').first()).toBeVisible()
    await page.locator('.retro-card__header').first().click()
    await expect(page.locator('.retro-card__body').first()).not.toBeVisible()
  })

  test('cards expand independently', async ({ page }) => {
    await page.locator('.retro-card__header').first().click()
    await expect(page.locator('.retro-card').first().locator('.retro-card__body')).toBeVisible()
    await expect(page.locator('.retro-card').nth(1).locator('.retro-card__body')).not.toBeVisible()
  })
})

test.describe('RetroView — Human comments section', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await page.locator('.retro-card__header').first().click()
    await expect(page.locator('.retro-card__body').first()).toBeVisible()
  })

  test('human comments section is open by default when card expands', async ({ page }) => {
    const body = page.locator('.retro-card__body').first()
    await expect(body.locator('.comment-thread').first()).toBeVisible()
  })

  test('bot comments are filtered out — copilot-swe-agent not shown', async ({ page }) => {
    await expect(
      page.locator('.comment__author').filter({ hasText: '@copilot-swe-agent' })
    ).not.toBeVisible()
  })

  test('bot comments are filtered out — github-actions[bot] not shown', async ({ page }) => {
    await expect(
      page.locator('.comment__author').filter({ hasText: '@github-actions[bot]' })
    ).not.toBeVisible()
  })

  test('human fork PR comments are shown', async ({ page }) => {
    await expect(
      page.locator('.comment__author').filter({ hasText: '@hadoku' }).first()
    ).toBeVisible()
    await expect(
      page.locator('.comment__body').filter({ hasText: 'Looks good to me' })
    ).toBeVisible()
  })

  test('human upstream PR comments are shown', async ({ page }) => {
    await expect(
      page.locator('.comment__author').filter({ hasText: '@upstream-maintainer' })
    ).toBeVisible()
    await expect(
      page.locator('.comment__body').filter({ hasText: 'Thanks for the contribution' })
    ).toBeVisible()
  })

  test('inline comment shows file path and line', async ({ page }) => {
    await expect(page.locator('.comment--inline')).toBeVisible()
    await expect(
      page.locator('.comment__location').filter({ hasText: 'src/request.js:55' })
    ).toBeVisible()
  })

  test('fork PR and upstream PR threads are labelled separately', async ({ page }) => {
    await expect(
      page.locator('.comment-thread__label').filter({ hasText: 'Fork PR' })
    ).toBeVisible()
    await expect(
      page.locator('.comment-thread__label').filter({ hasText: 'Upstream PR' })
    ).toBeVisible()
  })
})

test.describe('RetroView — Timeline section', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await page.locator('.retro-card__header').first().click()
  })

  test('timeline section is present', async ({ page }) => {
    // Click to open the timeline section (it's collapsed by default)
    const timelineToggle = page.locator('.retro-section__toggle').filter({ hasText: /Timeline/i })
    await expect(timelineToggle).toBeVisible()
    await timelineToggle.click()
    await expect(page.locator('.retro-timeline')).toBeVisible()
  })

  test('timeline shows at least the dispatched step', async ({ page }) => {
    const timelineToggle = page.locator('.retro-section__toggle').filter({ hasText: /Timeline/i })
    await timelineToggle.click()
    await expect(
      page.locator('.retro-timeline__label').filter({ hasText: 'Dispatched' })
    ).toBeVisible()
  })
})

test.describe('RetroView — Workflow chips', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await page.locator('.retro-card__header').first().click()
    // Open workflow section
    await page
      .locator('.retro-section__toggle')
      .filter({ hasText: /Copilot workflow/i })
      .click()
  })

  test('reproduced chip shows as yes', async ({ page }) => {
    await expect(
      page.locator('.workflow-chip--yes').filter({ hasText: /Reproduced/i })
    ).toBeVisible()
  })

  test('verified chip shows as yes', async ({ page }) => {
    await expect(page.locator('.workflow-chip--yes').filter({ hasText: /Verified/i })).toBeVisible()
  })

  test('self_corrected chip shows as no when false', async ({ page }) => {
    await expect(
      page.locator('.workflow-chip--no').filter({ hasText: /Self-corrected/i })
    ).toBeVisible()
  })

  test('step count is shown', async ({ page }) => {
    await expect(page.locator('.workflow-metrics__meta')).toContainText('15 steps')
  })
})

test.describe('RetroView — SA findings', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await page.locator('.retro-card__header').first().click()
    await page
      .locator('.retro-section__toggle')
      .filter({ hasText: /SA findings/i })
      .click()
  })

  test('SA findings section shows annotation', async ({ page }) => {
    await expect(page.locator('.sa-finding')).toBeVisible()
  })

  test('finding shows file path and line', async ({ page }) => {
    await expect(page.locator('.sa-finding__loc')).toContainText('src/request.js:42')
  })

  test('finding shows message', async ({ page }) => {
    await expect(page.locator('.sa-finding__msg')).toContainText('Unused variable')
  })
})

test.describe('RetroView — ContextPanel', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
    await navigateToRetro(page)
    await page.locator('.retro-card__header').first().click()
    // Open artifacts section
    await page
      .locator('.retro-section__toggle')
      .filter({ hasText: /Artifacts/i })
      .click()
  })

  test('context brief artifact link is shown', async ({ page }) => {
    await expect(
      page.locator('.retro-artifact-link').filter({ hasText: /Context brief/i })
    ).toBeVisible()
  })

  test('upstream PR body artifact link is shown', async ({ page }) => {
    await expect(
      page.locator('.retro-artifact-link').filter({ hasText: /Upstream PR body/i })
    ).toBeVisible()
  })

  test('clicking context brief opens ContextPanel', async ({ page }) => {
    await page
      .locator('.retro-artifact-link')
      .filter({ hasText: /Context brief/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await expect(page.locator('.context-panel__title')).toContainText('Context brief')
  })

  test('context panel shows the content', async ({ page }) => {
    await page
      .locator('.retro-artifact-link')
      .filter({ hasText: /Context brief/i })
      .click()
    await expect(page.locator('.context-panel__body')).toContainText('fork issue context brief')
  })

  test('clicking upstream PR body opens ContextPanel with that content', async ({ page }) => {
    await page
      .locator('.retro-artifact-link')
      .filter({ hasText: /Upstream PR body/i })
      .click()
    await expect(page.locator('.context-panel__title')).toContainText('Upstream PR body')
    await expect(page.locator('.context-panel__body')).toContainText('Fixes memory leak')
  })

  test('close button dismisses ContextPanel', async ({ page }) => {
    await page
      .locator('.retro-artifact-link')
      .filter({ hasText: /Context brief/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await page.locator('.context-panel__close').click()
    await expect(page.locator('.context-panel')).not.toBeVisible()
  })

  test('Escape key dismisses ContextPanel', async ({ page }) => {
    await page
      .locator('.retro-artifact-link')
      .filter({ hasText: /Context brief/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.locator('.context-panel')).not.toBeVisible()
  })

  test('clicking overlay backdrop dismisses ContextPanel', async ({ page }) => {
    await page
      .locator('.retro-artifact-link')
      .filter({ hasText: /Context brief/i })
      .click()
    await expect(page.locator('.context-panel')).toBeVisible()
    await page.locator('.context-panel-overlay').click()
    await expect(page.locator('.context-panel')).not.toBeVisible()
  })
})

test.describe('RetroView — Empty and pre-telemetry states', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllAPIs(page)
  })

  test('pre-telemetry card shows placeholder when retro has no timing', async ({ page }) => {
    await navigateToRetro(page)
    // Second card (vercel/next.js) has no timing data
    await page.locator('.retro-card__header').nth(1).click()
    await expect(page.locator('.retro-placeholder')).toBeVisible()
    await expect(page.locator('.retro-placeholder')).toContainText('before full telemetry')
  })

  test('empty batch shows no-issues message', async ({ page }) => {
    await page.route('**/dispatch/api/oss/retro/batch/**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          batch: mockRetroBatches[0],
          issues: [],
          owner: mockOwner
        })
      })
    })
    await navigateToRetro(page)
    await expect(page.locator('.retro-empty')).toContainText('No issues in this batch yet')
  })

  test('no human comments section shows appropriate message', async ({ page }) => {
    // Override with a card that has no comments
    await page.route('**/dispatch/api/oss/retro/batch/**', async route => {
      const detail = JSON.parse(JSON.stringify(mockRetroBatchDetail)) as typeof mockRetroBatchDetail
      detail.issues[0].retro.raw_comments = { fork_pr: [], upstream_pr: [] }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, ...detail, owner: mockOwner })
      })
    })
    await navigateToRetro(page)
    await page.locator('.retro-card__header').first().click()
    // Human comments section is open by default; with 0 comments it shows the empty message
    await expect(
      page.locator('.retro-empty-section').filter({ hasText: 'No human comments' })
    ).toBeVisible()
  })
})
