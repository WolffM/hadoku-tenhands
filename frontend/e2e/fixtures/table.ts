/**
 * The fixture corpus, minus the transport.
 *
 * This holds the route TABLE, the matcher, the `ok()` helper, and the response
 * types — everything that describes WHAT the mock API answers, with no opinion
 * on HOW it is served. `api.ts` layers Playwright's `page.route()` on top for
 * the e2e suite; `src/demo/fetchStub.ts` layers a `window.fetch` wrapper on top
 * for the static demo build. Both consume the exact same `defaultRoutes` and
 * `lookup()`, so the demo and the tests can never drift apart.
 *
 * There is deliberately NO `@playwright/test` import here.
 */

import * as d from './data'

/** Anything that survives JSON.stringify, plus a raw string for HTML bodies. */
export type ResponseBody =
  | string
  | number
  | boolean
  | null
  | readonly ResponseBody[]
  | { readonly [key: string]: ResponseBody }

/**
 * A response body, or a function of the request that produces one.
 *
 * Spelled out rather than `unknown | Fn`: a union containing `unknown` collapses
 * to `unknown`, which silently erases the function arm and leaves every
 * responder's `ctx` implicitly `any`.
 */
export type ResponderFn = (ctx: RequestContext) => ResponseBody
export type Responder = ResponseBody | ResponderFn

export interface RequestContext {
  method: string
  /** Path with the `/tenhands` prefix stripped, e.g. `/api/oss/stage1-targets`. */
  path: string
  /** Parsed query string. */
  query: URLSearchParams
  /** Parsed JSON body for POSTs, or undefined. */
  body: Record<string, unknown> | undefined
}

/** Route table entry. `path` may end in `/*` to match any single-or-multi segment tail. */
export type Table = Record<string, Responder>

/** The flat envelope most of the Flask API uses: `{ success, ...payload }`. */
export const ok = (extra: Record<string, unknown> = {}): ResponseBody => ({
  success: true,
  owner: 'test-user',
  ...extra
})

/**
 * Default response for every endpoint `src/api/endpoints.ts` can reach.
 *
 * Keys are `METHOD /path`. A trailing `/*` matches any remaining segments, which
 * is how the parameterised routes (dossier/:slug, temporal/issue/:id, …) are
 * expressed without a regex each.
 */
export const defaultRoutes: Table = {
  // ---- identity + health -------------------------------------------------
  'GET /api/owner': ok({ owner: d.mockOwner }),
  'GET /api/healthcheck': ok({ status: 'healthy', owner: d.mockOwner, api_version: '2.0.0' }),
  'GET /api/global-workflow-runs': ok({ runs: d.mockWorkflowRuns, owner: d.mockOwner }),

  // ---- vibecheck stages --------------------------------------------------
  'GET /api/stage1-repos': ok({ owner: d.mockOwner, repos: d.mockStage1Repos }),
  'GET /api/stage2-repos': ok({ owner: d.mockOwner, repos: d.mockStage2Repos }),
  'GET /api/stage3-issues': ok({
    owner: d.mockOwner,
    issues: d.mockStage3Issues,
    labels: ['vibeCheck', 'severity:critical', 'severity:high', 'severity:medium', 'severity:low'],
    repos_with_copilot_prs: []
  }),
  'GET /api/stage4-prs': ok({ owner: d.mockOwner, prs: d.mockStage4PRs }),
  'GET /api/pr-details': ok({ pr: d.mockPRDetails }),
  'POST /api/pr-details': ok({ pr: d.mockPRDetails }),

  // ---- vibecheck actions -------------------------------------------------
  'POST /api/install-vibecheck': ok({ message: 'Installed', installed: [] }),
  'POST /api/update-vibecheck': ok({ message: 'Updated', updated: [] }),
  'POST /api/run-vibecheck': ok({ message: 'Run dispatched', dispatched: [] }),
  'POST /api/assign-copilot': ok({ message: 'Assigned', assigned: [] }),
  'POST /api/approve-pr': ok({ message: 'Approved' }),
  'POST /api/mark-pr-ready': ok({ message: 'Marked ready' }),
  'POST /api/merge-pr': ok({ message: 'Merged' }),

  // ---- OSS recon pipeline ------------------------------------------------
  'GET /api/oss/stage1-targets': ok({ targets: d.mockOSSTargets }),
  'GET /api/oss/stage2-issues': ok({ issues: d.mockOSSScoredIssues }),
  'GET /api/oss/stage5-tracking': ok({ submitted: d.mockOSSSubmittedPRs }),
  'GET /api/oss/pipeline-status': ok({ statuses: d.mockPipelineStatuses }),
  'GET /api/oss/retrospective-logs': ok({ logs: d.mockRetrospectiveLogs }),
  'GET /api/oss/dossier/*': ok({
    dossier: {
      slug: 'acme-corp-widget-api',
      generatedAt: '2026-08-01T00:00:00.000Z',
      sections: {
        overview: 'Popular Node.js framework for building web applications.',
        contributionRules: 'Follow the style guide and add tests.',
        successPatterns: 'Small focused PRs with clear descriptions.',
        antiPatterns: 'Avoid large refactors without prior discussion.',
        issueBoard: 'Check the good first issue label.',
        environmentSetup: 'Run npm install && npm test.'
      }
    }
  }),
  'GET /api/oss/issue-brief/*': ok({ data: d.mockOSSIssueBrief }),
  // Served as HTML, not JSON — it is a standalone report document.
  'GET /api/oss/issue-report/*': '<!DOCTYPE html><title>Pipeline Report</title><div>report</div>',
  'POST /api/oss/compute-target': ok({ message: 'Computed' }),
  'POST /api/oss/refresh-target': ok({ message: 'Refreshed' }),
  'POST /api/oss/select-issue': ok({ message: 'Selected' }),
  'POST /api/oss/fork-and-assign': ok({ message: 'Forked and assigned' }),
  'POST /api/oss/advance-pipeline': ok({ message: 'Advanced' }),
  'POST /api/oss/poll-submitted-prs': ok({ submitted: d.mockOSSSubmittedPRs }),
  'POST /api/oss/signoff': ok({ message: 'Signed off' }),

  // ---- retrospectives ----------------------------------------------------
  'GET /api/oss/retro/batches': ok({ batches: d.mockRetroBatches }),
  'GET /api/oss/retro/batch/*': ok({ ...d.mockRetroBatchDetail }),
  // Always stubbed: the real handler shells out to `gh api`, which blocks
  // single-threaded Flask for the length of the call and starves every
  // request behind it. Commit data is covered by retro_report.py's own tests.
  'GET /api/oss/retro/pr-commits/*': ok({ commits: [] }),

  // ---- task automation ---------------------------------------------------
  // Both of these ARE the response — the client returns them whole, so they
  // must not be nested under another key.
  'GET /api/taskauto/status': d.mockTaskAutoStatus,
  // Answers for the task actually asked for. A fixed body would make the modal
  // show one task's detail under another's heading, so a spec could only ever
  // click the one row the fixture happened to describe.
  'GET /api/taskauto/task/*': ({ path }) => {
    const taskId = decodeURIComponent(path.split('/').pop() ?? '')
    const known = d.mockTaskAutoStatus.boards
      .flatMap(b => Object.values(b.lanes).flat())
      .find(t => t.id === taskId)
    if (!known) return d.mockTaskAutoDetail
    return {
      ...d.mockTaskAutoDetail,
      task: { ...d.mockTaskAutoDetail.task, id: known.id, title: known.title }
    }
  },
  'POST /api/taskauto/merge': ok({ message: 'Merged' }),
  // The in-app review modal fetches one PR's diff + its plan by repo+number.
  // Like status, this IS the response — flat, not nested under `data`.
  'GET /api/taskauto/pr-details': ({ query }) =>
    d.mockTaskAutoPRDetail(query.get('repo') ?? '', Number(query.get('number') ?? 0)),
  'POST /api/taskauto/send-back': ok({ message: 'Sent back to stalled' }),

  // ---- temporal ----------------------------------------------------------
  'GET /api/temporal/batches': ok({ batches: d.mockTemporalBatches }),
  'GET /api/temporal/batch/*': ok(d.mockTemporalBatchDetail),
  'GET /api/temporal/inbox': ok({
    items: d.mockTemporalInboxItems,
    count: d.mockTemporalInboxItems.length
  }),
  'GET /api/temporal/issue/*': ok(d.mockTemporalIssueDetail),
  // Covers `POST /api/temporal/issue/<id>/signal`. The body is captured by the
  // router, so a spec asserts the decision via `api.posts` rather than by
  // stashing calls on `window` the way the previous fixture had to.
  'POST /api/temporal/issue/*': ({ body }) =>
    ok({
      workflow_id: null,
      decision: typeof body?.decision === 'string' ? body.decision : null
    }),
  'GET /api/temporal/evidence/*': ok({ evidence: [] }),

  // ---- diagnostics the harness itself pokes ------------------------------
  'GET /api/oss/debug/gh-health': ok({ authenticated: true, api_working: true })
}

/**
 * Look a request up in the table. Exact match wins; otherwise the longest
 * `/*` prefix wins, so `GET /api/temporal/issue/*` cannot shadow a more
 * specific entry added later.
 */
export function lookup(table: Table, method: string, path: string): Responder | undefined {
  const exact = table[`${method} ${path}`]
  if (exact !== undefined) return exact

  let best: { key: string; responder: Responder } | undefined
  for (const [key, responder] of Object.entries(table)) {
    if (!key.endsWith('/*')) continue
    const [m, pattern] = key.split(' ')
    if (m !== method) continue
    const prefix = pattern.slice(0, -1) // keep the trailing slash
    if (!path.startsWith(prefix)) continue
    if (!best || prefix.length > best.key.length) best = { key: prefix, responder }
  }
  return best?.responder
}
