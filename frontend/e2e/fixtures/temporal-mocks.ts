/**
 * Temporal (crimson-kitty) API Mocks for Playwright Tests.
 *
 * Routes mocked:
 *   GET  /api/temporal/health
 *   GET  /api/temporal/batches
 *   GET  /api/temporal/batch/<batch_id>
 *   GET  /api/temporal/issue/<batch_id>/<issue_id>
 *   GET  /api/temporal/inbox
 *   POST /api/temporal/dispatch          (echo)
 *   POST /api/temporal/issue/.../signal  (records calls on `window`)
 */

import type { Page } from '@playwright/test'

export const mockTemporalBatches = [
  { batch_id: 'crimson-kitty', issue_count: 3, deferred_count: 1, active: true },
  { batch_id: 'smoke-1', issue_count: 1, deferred_count: 0, active: false }
]

export const mockTemporalBatchDetail = {
  batch_id: 'crimson-kitty',
  issue_count: 3,
  issues: [
    {
      batch_id: 'crimson-kitty',
      issue_id: 'microsoft__markitdown-183',
      current_state: 'submittable',
      is_deferred: false,
      deferred_at: null,
      deferred_gate: null,
      transition_count: 9,
      gate_count: 12
    },
    {
      batch_id: 'crimson-kitty',
      issue_id: 'acme-corp__widget-api-42',
      current_state: 'awaiting_human_review',
      is_deferred: true,
      deferred_at: 'fixed',
      deferred_gate: 'relevance',
      transition_count: 5,
      gate_count: 6
    },
    {
      batch_id: 'crimson-kitty',
      issue_id: 'zeit__next-7',
      current_state: 'aborted',
      is_deferred: false,
      deferred_at: null,
      deferred_gate: null,
      transition_count: 3,
      gate_count: 2
    }
  ]
}

const sampleDiff = `diff --git a/src/foo.ts b/src/foo.ts
--- a/src/foo.ts
+++ b/src/foo.ts
@@ -1,3 +1,4 @@
 export function foo() {
-  return 1
+  return 2
 }
`

export const mockTemporalIssueDetail = {
  batch_id: 'crimson-kitty',
  issue_id: 'microsoft__markitdown-183',
  current_state: 'submittable',
  is_deferred: false,
  deferred_at: null,
  deferred_gate: null,
  transition_count: 3,
  gate_count: 3,
  transitions: [
    {
      from: 'candidate',
      to: 'eligible',
      reason: 'eligibility gate passed',
      decided_by: 'gate:eligibility',
      ts: '2026-04-14T10:00:00Z'
    },
    {
      from: 'eligible',
      to: 'forked',
      reason: 'fork ensured + brief scrubbed',
      decided_by: 'activity:fork_and_scrub_brief',
      ts: '2026-04-14T10:01:00Z'
    },
    {
      from: 'forked',
      to: 'fixed',
      reason: 'agent produced diff with 2 commits',
      decided_by: 'activity:agent_fix',
      ts: '2026-04-14T10:05:00Z'
    }
  ],
  gates: [
    {
      gate: 'eligibility',
      verdict: 'pass',
      reason: 'repo passes all eligibility checks',
      evidence_data: { ai_policy: 'allowed', dco_required: false },
      ts: '2026-04-14T10:00:00Z'
    },
    {
      gate: 'diff_non_empty',
      verdict: 'pass',
      reason: '2 commits, 1 file changed',
      evidence_data: sampleDiff,
      ts: '2026-04-14T10:05:00Z'
    },
    {
      gate: 'relevance',
      verdict: 'defer',
      reason: 'judge returned low confidence on relevance',
      evidence_data: { score: 0.55, files_touched: ['src/foo.ts'] },
      ts: '2026-04-14T10:06:00Z'
    }
  ],
  events: [
    { ts: '2026-04-14T10:00:00Z', type: 'workflow_started' },
    { ts: '2026-04-14T10:06:00Z', type: 'defer_notified' }
  ]
}

export const mockTemporalInboxItems = [
  {
    batch_id: 'crimson-kitty',
    issue_id: 'acme-corp__widget-api-42',
    workflow_id: 'issue-crimson-kitty-acme-corp__widget-api-42',
    state: 'fixed',
    gate: 'relevance',
    reason: 'judge returned low confidence',
    queued_at: '2026-04-14T10:10:00Z'
  },
  {
    batch_id: 'crimson-kitty',
    issue_id: 'zeit__next-7',
    workflow_id: 'issue-crimson-kitty-zeit__next-7',
    state: 'submittable',
    gate: 'submission_judge',
    reason: 'PR body fails template compliance',
    queued_at: '2026-04-14T10:12:00Z'
  },
  {
    batch_id: 'smoke-1',
    issue_id: 'microsoft__markitdown-183',
    workflow_id: 'issue-smoke-1-microsoft__markitdown-183',
    state: 'fixed',
    gate: 'relevance',
    reason: 'unrelated imports detected',
    queued_at: '2026-04-14T10:15:00Z'
  },
  {
    batch_id: 'crimson-kitty-signoff',
    issue_id: 'microsoft__terminal-5301',
    workflow_id: 'issue-crimson-kitty-signoff-microsoft__terminal-5301',
    state: 'awaiting_signoff',
    gate: 'operator_signoff',
    reason: 'preview PR ready on fork; edit if needed, then approve to ship upstream',
    queued_at: '2026-04-26T18:00:00Z',
    operator_pr_url: 'https://github.com/WolffM/microsoft-terminal/pull/9',
    pr_title: 'fix: Tab close button stops responding after switching profiles',
    pr_body_excerpt:
      '## Summary\n\nThe tab close button became unresponsive after switching profiles because the click handler was bound to the old profile context. This change rebinds it on profile change.\n\n## Root cause\n\nProfileSwitchEvent invalidated...'
  }
]

function envelope<T>(data: T) {
  return JSON.stringify({ success: true, data, _meta: {} })
}

export async function mockTemporalAPIs(page: Page): Promise<void> {
  await page.route('**/tenhands/api/temporal/health', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope({
        state_root: 'state',
        state_root_exists: true,
        batch_count: mockTemporalBatches.length,
        cluster_check: 'skipped'
      })
    })
  })

  await page.route('**/tenhands/api/temporal/batches', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope({ batches: mockTemporalBatches })
    })
  })

  await page.route('**/tenhands/api/temporal/batch/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope(mockTemporalBatchDetail)
    })
  })

  await page.route('**/tenhands/api/temporal/issue/*/*', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope(mockTemporalIssueDetail)
    })
  })

  await page.route('**/tenhands/api/temporal/inbox', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope({
        items: mockTemporalInboxItems,
        count: mockTemporalInboxItems.length
      })
    })
  })

  // Signal endpoint: record the call on `window.__temporalSignals` and return OK.
  const signalPattern = /\/issue\/([^/]+)\/signal/
  await page.route('**/tenhands/api/temporal/issue/*/signal', async route => {
    const req = route.request()
    const body = (req.postDataJSON() ?? {}) as { decision?: string }
    const url = req.url()
    const match = signalPattern.exec(url)
    const workflowId = match ? decodeURIComponent(match[1]) : null
    await page.evaluate(
      (call: { workflowId: string | null; decision: string | undefined }) => {
        const w = window as unknown as {
          __temporalSignals?: { workflowId: string | null; decision: string | undefined }[]
        }
        w.__temporalSignals = w.__temporalSignals ?? []
        w.__temporalSignals.push(call)
      },
      { workflowId, decision: body.decision }
    )
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: envelope({ workflow_id: workflowId, decision: body.decision })
    })
  })

  await page.route('**/tenhands/api/temporal/dispatch', async route => {
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: envelope({
        batch_id: 'crimson-kitty',
        workflow_id: 'batch-crimson-kitty',
        issue_count: 0
      })
    })
  })
}
