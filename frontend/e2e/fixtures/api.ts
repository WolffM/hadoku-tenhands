/**
 * The local suite's API layer: one route handler, default-deny.
 *
 * WHY THIS SHAPE. The suite this replaces mocked endpoints opt-in, one
 * `page.route()` per endpoint per helper, and `mockAllAPIs()` wired up a subset
 * of them. Anything the UI called that no helper had claimed fell straight
 * through to the real Flask backend on :5001, which answers an unauthenticated
 * request with 401. The 401 logged a console error, and the console-error
 * fixture in `base.ts` failed the test — so a missing MOCK was reported as a
 * failing ASSERTION, in a spec that often had nothing to do with the endpoint.
 * Roughly 120 of 180 tests failed that way, all reading like product bugs.
 *
 * The fix is to make the mock layer total rather than additive:
 *
 *   1. ONE route covering every /tenhands/api path, so nothing reaches the
 *      network. A
 *      test cannot silently depend on a live backend any more.
 *   2. Every endpoint in `src/api/endpoints.ts` has a default response below.
 *      Views are free to fetch whatever they fetch.
 *   3. A request that matches no entry is NOT passed through and NOT quietly
 *      stubbed — it is recorded and fails the test by name, at teardown, with
 *      the method and path. A new endpoint shows up as "you forgot to mock
 *      GET /api/whatever", once, in the spec that triggered it.
 *
 * That last point is the whole design. The old suite's failure mode was that a
 * gap in the mocks was indistinguishable from a broken UI; here a gap says
 * exactly what it is.
 */

import type { Page, Route } from '@playwright/test'

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
type Table = Record<string, Responder>

/** The flat envelope most of the Flask API uses: `{ success, ...payload }`. */
const ok = (extra: Record<string, unknown> = {}): ResponseBody => ({
  success: true,
  owner: 'test-user',
  ...extra
})

/**
 * The temporal routes use a DIFFERENT envelope — `{ success, data, _meta }` —
 * and the client unwraps `.data`. Mixing the two up produces an empty view
 * rather than an error, so they get their own helper rather than a comment.
 */
const enveloped = (data: unknown): ResponseBody =>
  ({ success: true, data, _meta: {} }) as ResponseBody

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
  'POST /api/clear-cache': ok({ message: 'Cache cleared' }),
  'POST /api/workflow-status': ok({ runs: d.mockWorkflowRuns, status: 'completed' }),

  // ---- OSS recon pipeline ------------------------------------------------
  'GET /api/oss/stage1-targets': ok({ targets: d.mockOSSTargets }),
  'GET /api/oss/stage2-issues': ok({ issues: d.mockOSSScoredIssues }),
  'GET /api/oss/stage3-assigned': ok({ assignments: d.mockOSSAssignments }),
  'GET /api/oss/stage4-fork-prs': ok({ prs: d.mockOSSForkPRs }),
  'GET /api/oss/stage5-submit': ok({
    ready: d.mockOSSReadyToSubmit,
    submitted: d.mockOSSSubmittedPRs
  }),
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
  'GET /api/oss/fork-pr-details': ok({ pr: d.mockOSSForkPRDetails }),
  'POST /api/oss/fork-pr-details': ok({ pr: d.mockOSSForkPRDetails }),
  'POST /api/oss/compute-target': ok({ message: 'Computed' }),
  'POST /api/oss/refresh-target': ok({ message: 'Refreshed' }),
  'POST /api/oss/select-issue': ok({ message: 'Selected' }),
  'POST /api/oss/fork-and-assign': ok({ message: 'Forked and assigned' }),
  'POST /api/oss/advance-pipeline': ok({ message: 'Advanced' }),
  'POST /api/oss/approve-fork-pr': ok({ message: 'Approved' }),
  'POST /api/oss/merge-fork-pr': ok({ message: 'Merged' }),
  'POST /api/oss/submit-to-origin': ok({ message: 'Submitted' }),
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

  // ---- temporal (note: `enveloped`, not `ok`) ----------------------------
  'GET /api/temporal/health': enveloped({
    state_root: 'state',
    state_root_exists: true,
    batch_count: d.mockTemporalBatches.length,
    cluster_check: 'skipped'
  }),
  'GET /api/temporal/batches': enveloped({ batches: d.mockTemporalBatches }),
  'GET /api/temporal/batch/*': enveloped(d.mockTemporalBatchDetail),
  'GET /api/temporal/inbox': enveloped({
    items: d.mockTemporalInboxItems,
    count: d.mockTemporalInboxItems.length
  }),
  'GET /api/temporal/issue/*': enveloped(d.mockTemporalIssueDetail),
  // Covers `POST /api/temporal/issue/<id>/signal`. The body is captured by the
  // router, so a spec asserts the decision via `api.posts` rather than by
  // stashing calls on `window` the way the previous fixture had to.
  'POST /api/temporal/issue/*': ({ body }) =>
    enveloped({
      workflow_id: null,
      decision: typeof body?.decision === 'string' ? body.decision : null
    }),
  'POST /api/temporal/dispatch': enveloped({
    batch_id: 'crimson-kitty',
    workflow_id: 'batch-crimson-kitty',
    issue_count: 0
  }),
  'GET /api/temporal/evidence/*': enveloped({ evidence: [] }),

  // ---- diagnostics the harness itself pokes ------------------------------
  'GET /api/oss/debug/gh-health': ok({ authenticated: true, api_working: true })
}

/**
 * Look a request up in the table. Exact match wins; otherwise the longest
 * `/*` prefix wins, so `GET /api/temporal/issue/*` cannot shadow a more
 * specific entry added later.
 */
function lookup(table: Table, method: string, path: string): Responder | undefined {
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

export interface MockHandle {
  /** Requests that matched no table entry. Asserted empty by the base fixture. */
  readonly unmocked: string[]
  /** Every request served, as `METHOD /path` — for asserting a call happened. */
  readonly calls: string[]
  /** Bodies of POSTs served, keyed by `METHOD /path`, newest last. */
  readonly posts: { key: string; body: Record<string, unknown> | undefined }[]
}

/**
 * Install the router on a page. `overrides` are merged over `defaultRoutes`,
 * which is how a spec says "this endpoint, for this test, returns that" without
 * re-declaring the other fifty.
 */
export async function installApi(page: Page, overrides: Table = {}): Promise<MockHandle> {
  const table: Table = { ...defaultRoutes, ...overrides }
  const unmocked: string[] = []
  const calls: string[] = []
  const posts: { key: string; body: Record<string, unknown> | undefined }[] = []

  await page.route('**/tenhands/api/**', async (route: Route) => {
    const request = route.request()
    const method = request.method()
    const url = new URL(request.url())
    const path = url.pathname.replace(/^.*?\/tenhands/, '')

    let body: Record<string, unknown> | undefined
    if (method === 'POST') {
      try {
        body = request.postDataJSON() as Record<string, unknown>
      } catch {
        body = undefined
      }
    }

    const responder = lookup(table, method, path)
    const key = `${method} ${path}`

    if (responder === undefined) {
      unmocked.push(key)
      // Abort rather than fulfil with an error status. A 4xx/5xx would make the
      // app log a console error, and the console-error fixture would then report
      // a mock gap as an assertion failure — exactly the confusion this replaces.
      // The teardown check below is the one that speaks.
      await route.abort('failed')
      return
    }

    calls.push(key)
    if (method === 'POST') posts.push({ key, body })

    const payload =
      typeof responder === 'function'
        ? responder({
            method,
            path,
            query: url.searchParams,
            body
          })
        : responder

    // Not everything under /api is JSON — the issue report is a standalone HTML
    // document. Serving it as application/json would make the client's
    // `res.json()` throw, which reads as a product bug rather than a fixture one.
    const isHtml = typeof payload === 'string' && payload.trimStart().startsWith('<')

    await route.fulfill({
      status: 200,
      contentType: isHtml ? 'text/html' : 'application/json',
      body: isHtml ? payload : JSON.stringify(payload)
    })
  })

  return { unmocked, calls, posts }
}
