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
// The real pipeline report, straight from the backend generator (fetched from
// prod), with the third-party repo/issue identifiers rewritten to the demo's
// acme-corp/widget-api #1234 so it's authentic but demo-consistent and safe to
// share. Served for the OSS "Report" modal (rendered inline via srcdoc).
import issueReportHtml from './issue-report.html?raw'

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
 * A realistic 6-section dossier for the OSS Contributions view. Each section is
 * rendered as markdown, so these read like the aggregator's real output rather
 * than the one-line placeholders the default fixture carries. Subject is the
 * demo's target repo (acme-corp/widget-api).
 */
const dossier: ResponseBody = {
  slug: 'acme-corp-widget-api',
  generatedAt: new Date(Date.now() - 3600000).toISOString(),
  sections: {
    overview: [
      '**acme-corp/widget-api** is a mid-sized TypeScript HTTP framework — ~48k',
      'lines across 320 files, 6.1k stars, 214 contributors. It ships roughly',
      'every three weeks and the maintainers are responsive: median time-to-first',
      'review on a PR is **under 48 hours**.',
      '',
      '- **Health:** actively maintained (last release 9 days ago)',
      '- **Test suite:** Vitest, ~92% line coverage, green on `main`',
      '- **CI:** lint + typecheck + unit + a contract-test matrix on Node 18/20/22',
      '- **Review culture:** small PRs land fast; large refactors are asked to',
      '  open a discussion first.'
    ].join('\n'),
    contributionRules: [
      '### From CONTRIBUTING.md',
      '',
      '1. **One change per PR.** Unrelated fixes get asked to split.',
      '2. **Conventional commits** are required (`fix:`, `feat:`, `docs:` …); the',
      '   title becomes the squash-merge subject.',
      '3. **DCO sign-off** (`git commit -s`) is enforced by a bot check.',
      '4. Every bug fix ships **with the test that would have caught it**.',
      '5. Run `pnpm verify` (lint + typecheck + test) before pushing — CI runs the',
      '   same three gates and a red one blocks review.'
    ].join('\n'),
    successPatterns: [
      'What recently-merged PRs had in common:',
      '',
      '- A **failing test added first**, then the fix — reviewers merged these',
      '  fastest.',
      '- A one-paragraph problem statement linking the issue, not just a diff.',
      '- Touching **one module**. `middleware/` and `router/` fixes with a focused',
      '  diff (< 80 lines) had a ~70% merge rate.',
      '- Matching the surrounding style exactly; no drive-by reformatting.'
    ].join('\n'),
    antiPatterns: [
      'What got PRs closed or stalled:',
      '',
      '- **Large refactors** opened cold, with no prior issue or discussion.',
      '- Bumping dependencies alongside a behavior fix (split these).',
      '- Reformatting whole files — the diff drowns the actual change.',
      '- Fixing the symptom in the caller instead of the root cause in the module.',
      '- No test, or a test that passes with and without the change.'
    ].join('\n'),
    issueBoard: [
      '### Candidate issues (scored)',
      '',
      '| # | Title | Signal | Difficulty |',
      '| --- | --- | --- | --- |',
      /* check-icons-disable-next-line — a GitHub reaction count reproduced in the
         aggregator's dossier markdown. The emoji IS the datum here (it names which
         reaction was counted), it renders through the markdown pipeline, and no
         registry icon can stand in for it. */
      '| 1234 | Merged cells dropped in table renderer | `good first issue`, 8 👍 | Low |',
      '| 1198 | Pagination off-by-one on the final page | reproducible, has repro | Low |',
      '| 1150 | Timeout not propagated to sub-requests | `help wanted` | Medium |',
      '',
      'The top two are self-contained bugs with clear repro steps and an obvious',
      'test — the profile the pipeline dispatches best against.'
    ].join('\n'),
    environmentSetup: [
      'Node 20 + pnpm. Clone the fork, install, and run the suite:',
      '',
      '    pnpm install --frozen-lockfile',
      '    pnpm build',
      '    pnpm test',
      '',
      'Single-file iteration while fixing:',
      '',
      '    pnpm vitest run src/router/match.test.ts',
      '',
      'No services or containers are needed — the suite is fully in-process.'
    ].join('\n')
  }
}

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

  // ---- OSS dossier: a realistic 6-section brief, not the placeholder ------
  'GET /api/oss/dossier/*': ok({ dossier }),

  // ---- OSS issue report: a real-looking report for the Report modal ------
  'GET /api/oss/issue-report/*': issueReportHtml,

  // ---- retrospectives: the headline batch numbers, reconciled ------------
  'GET /api/oss/retro/batches': ok({ batches: retroBatches })
}
