/**
 * Curated showcase deltas, merged OVER `defaultRoutes` by the demo fetch stub.
 *
 * WHY HERE, not in `e2e/fixtures/data.ts`: the e2e specs assert against the
 * counts and owners in data.ts, so editing data.ts to read nicely for a public
 * demo would turn the suite red. Curation belongs on this side of the split.
 * Every shape below mirrors the corresponding `data.ts` shape exactly — this is
 * the same corpus with the owner rebranded to `WolffM` and the headline batch
 * numbers reconciled to the real pipeline outcomes.
 */

import * as d from '../../e2e/fixtures/data'
import { ok, type Table, type ResponseBody } from '../../e2e/fixtures/table'

const OWNER = 'WolffM'

/** Rewrite the fixtures' `test-user` GitHub org to the real one in a URL. */
const rebrand = (url: string): string => url.replace(/test-user/g, OWNER)

const workflowRuns = d.mockWorkflowRuns.map(run => ({ ...run, url: rebrand(run.url) }))

// The fork-issue links and PR URLs are rendered as clickable anchors, so their
// `test-user` org would show through in the UI; rebrand those to WolffM.
const pipelineStatuses = d.mockPipelineStatuses.map(s => ({
  ...s,
  forkIssueUrl: rebrand(s.forkIssueUrl)
}))

const prDetails = { ...d.mockPRDetails, url: rebrand(d.mockPRDetails.url) }

/**
 * The retrospective batch list — the headline of the OSS Contributions view.
 * `jade-hare` was the big 55-issue run; only one contribution reached and
 * survived upstream review. `crimson-kitty` is the smaller, fully-instrumented
 * batch whose detail view (below, unchanged from data.ts) carries full gates,
 * timing, and PR comment evidence.
 */
const retroBatches: ResponseBody = [
  {
    batch_id: 'crimson-kitty',
    created_at: new Date(Date.now() - 86400000).toISOString(),
    note: 'Active batch — full telemetry (gates, timing, review evidence)',
    issue_count: 2,
    upstream_pr_count: 1,
    upstream_merged: 1,
    upstream_closed: 0,
    upstream_open: 0,
    has_fork_pr: 2
  },
  {
    batch_id: 'jade-hare',
    created_at: new Date(Date.now() - 864000000).toISOString(),
    note: '55-issue run, Mar 13–17 2026 — 1 merged upstream',
    issue_count: 55,
    upstream_pr_count: 12,
    upstream_merged: 1,
    upstream_closed: 9,
    upstream_open: 2,
    has_fork_pr: 40
  }
]

/**
 * The overrides table. Keys and shapes match `defaultRoutes`; only the values
 * that need rebranding or reconciling to the real story are present here.
 */
export const overrides: Table = {
  // ---- identity + health: rebrand owner to WolffM ------------------------
  'GET /api/owner': ok({ owner: OWNER }),
  'GET /api/healthcheck': ok({ status: 'healthy', owner: OWNER, api_version: '2.0.0' }),
  'GET /api/global-workflow-runs': ok({ runs: workflowRuns, owner: OWNER }),

  // ---- vibecheck stages: rebrand owner -----------------------------------
  'GET /api/stage1-repos': ok({ owner: OWNER, repos: d.mockStage1Repos }),
  'GET /api/stage2-repos': ok({ owner: OWNER, repos: d.mockStage2Repos }),
  'GET /api/stage3-issues': ok({
    owner: OWNER,
    issues: d.mockStage3Issues,
    labels: ['vibeCheck', 'severity:critical', 'severity:high', 'severity:medium', 'severity:low'],
    repos_with_copilot_prs: []
  }),
  'GET /api/stage4-prs': ok({ owner: OWNER, prs: d.mockStage4PRs }),
  'GET /api/pr-details': ok({ pr: prDetails }),
  'POST /api/pr-details': ok({ pr: prDetails }),

  // ---- OSS pipeline: rebrand fork-issue links ----------------------------
  'GET /api/oss/pipeline-status': ok({ statuses: pipelineStatuses }),

  // ---- retrospectives: the headline batch numbers, reconciled ------------
  'GET /api/oss/retro/batches': ok({ batches: retroBatches })
}
