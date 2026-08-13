/**
 * Mock data for the local e2e suite.
 *
 * Data only — no Playwright import, no routing. `api.ts` owns the wiring, and
 * keeping the two apart is what lets the router be exhaustive: a response body
 * and the decision to serve it are separate concerns, and the file this
 * replaced conflated them into one opt-in helper per endpoint. Every endpoint
 * the UI can call is answered from here, whether or not a spec expects it.
 */

// ============ Mock Data ============

export const mockOwner = 'test-user'

export const mockStage1Repos = [
  { name: 'repo-without-vc-1', description: 'Test repo 1', isPrivate: false },
  { name: 'repo-without-vc-2', description: 'Test repo 2 (private)', isPrivate: true },
  { name: 'repo-without-vc-3', description: 'Test repo 3', isPrivate: false }
]

export const mockStage2Repos = [
  {
    name: 'repo-with-vc-1',
    description: 'Repo with vibecheck',
    isPrivate: false,
    lastRun: {
      status: 'completed',
      conclusion: 'success',
      createdAt: new Date(Date.now() - 86400000).toISOString()
    },
    commitsSinceLastRun: 3
  },
  {
    name: 'repo-with-vc-2',
    description: 'Another repo with vibecheck',
    isPrivate: false,
    lastRun: {
      status: 'completed',
      conclusion: 'failure',
      createdAt: new Date(Date.now() - 172800000).toISOString()
    },
    commitsSinceLastRun: 7
  }
]

export const mockStage3Issues = [
  {
    number: 42,
    title: 'Security vulnerability in auth module',
    repo: 'repo-with-vc-1',
    labels: [{ name: 'vibeCheck' }, { name: 'severity:critical' }],
    assignees: [],
    createdAt: new Date(Date.now() - 86400000).toISOString()
  },
  {
    number: 15,
    title: 'Performance issue in API handler',
    repo: 'repo-with-vc-1',
    labels: [{ name: 'vibeCheck' }, { name: 'severity:high' }],
    assignees: [],
    createdAt: new Date(Date.now() - 172800000).toISOString()
  },
  {
    number: 8,
    title: 'Code style improvements',
    repo: 'repo-with-vc-2',
    labels: [{ name: 'vibeCheck' }, { name: 'severity:low' }],
    assignees: [],
    createdAt: new Date(Date.now() - 259200000).toISOString()
  }
]

export const mockStage4PRs = [
  {
    number: 101,
    title: 'Fix security vulnerability in auth module',
    repo: 'repo-with-vc-1',
    author: { login: 'copilot[bot]' },
    isDraft: false,
    copilotCompleted: true,
    reviewDecision: null,
    headRefName: 'fix/auth-security',
    baseRefName: 'main',
    createdAt: new Date(Date.now() - 3600000).toISOString(),
    additions: 45,
    deletions: 12,
    changedFiles: 3
  },
  {
    number: 102,
    title: '[WIP] Fix performance issue',
    repo: 'repo-with-vc-1',
    author: { login: 'copilot[bot]' },
    isDraft: true,
    copilotCompleted: false,
    reviewDecision: null,
    headRefName: 'fix/perf-issue',
    baseRefName: 'main',
    createdAt: new Date(Date.now() - 7200000).toISOString(),
    additions: 20,
    deletions: 5,
    changedFiles: 2
  }
]

export const mockWorkflowRuns = [
  {
    id: 1,
    repo: 'repo-with-vc-1',
    workflowName: 'vibeCheck',
    status: 'completed',
    conclusion: 'success',
    createdAt: new Date(Date.now() - 3600000).toISOString(),
    url: 'https://github.com/test-user/repo-with-vc-1/actions/runs/1',
    vibecheck_installed: true
  },
  {
    id: 2,
    repo: 'repo-with-vc-2',
    workflowName: 'vibeCheck',
    status: 'completed',
    conclusion: 'failure',
    createdAt: new Date(Date.now() - 7200000).toISOString(),
    url: 'https://github.com/test-user/repo-with-vc-2/actions/runs/2',
    vibecheck_installed: true
  },
  {
    id: 3,
    repo: 'repo-with-vc-1',
    workflowName: 'CI',
    status: 'in_progress',
    conclusion: null,
    createdAt: new Date(Date.now() - 1800000).toISOString(),
    url: 'https://github.com/test-user/repo-with-vc-1/actions/runs/3',
    vibecheck_installed: true
  }
]

export const mockPRDetails = {
  number: 101,
  title: 'Fix security vulnerability in auth module',
  body: 'This PR fixes the security vulnerability by adding proper input validation.',
  repo: 'repo-with-vc-1',
  author: { login: 'copilot[bot]' },
  createdAt: new Date(Date.now() - 3600000).toISOString(),
  headRefName: 'fix/auth-security',
  baseRefName: 'main',
  files: [
    { path: 'src/auth/validator.ts', additions: 30, deletions: 5 },
    { path: 'src/auth/handler.ts', additions: 10, deletions: 5 },
    { path: 'tests/auth.test.ts', additions: 5, deletions: 2 }
  ],
  commits: 1,
  reviewDecision: null,
  state: 'open',
  url: 'https://github.com/test-user/repo-with-vc-1/pull/101',
  isDraft: false,
  additions: 45,
  deletions: 12,
  changedFiles: 3,
  diff: `diff --git a/src/auth/validator.ts b/src/auth/validator.ts
index abc123..def456 100644
--- a/src/auth/validator.ts
+++ b/src/auth/validator.ts
@@ -1,5 +1,35 @@
+import { sanitize } from './utils'
+
 export function validateInput(input: string): boolean {
-  return input.length > 0
+  if (!input || typeof input !== 'string') {
+    return false
+  }
+  const sanitized = sanitize(input)
+  return sanitized.length > 0 && sanitized.length < 1000
 }`
}

// ============ OSS Pipeline Mock Data ============

export const mockOSSTargets = [
  {
    slug: 'acme-corp-widget-api',
    health: {
      maintainerHealthScore: 85,
      mergeAccessibilityScore: 72,
      availabilityScore: 90,
      overallViability: 82,
      analyzedAt: new Date(Date.now() - 86400000).toISOString()
    },
    dossier: {
      sections: {
        overview: 'Popular Node.js framework for building web applications.',
        contributionRules: 'Follow the style guide and add tests.',
        successPatterns: 'Small focused PRs with clear descriptions.',
        antiPatterns: 'Avoid large refactors without prior discussion.',
        issueBoard: 'Check the good first issue label.',
        environmentSetup: 'Run npm install && npm test.'
      },
      completeness: {
        overview: true,
        contributionRules: true,
        successPatterns: true,
        antiPatterns: true,
        issueBoard: true,
        environmentSetup: true
      }
    },
    _meta: {
      computedAt: new Date(Date.now() - 43200000).toISOString()
    },
    meta: {
      stars: 31000,
      language: 'JavaScript',
      license: 'MIT',
      openIssueCount: 156,
      hasContributing: true
    }
  },
  {
    slug: 'vercel-next.js',
    health: {
      maintainerHealthScore: 60,
      mergeAccessibilityScore: 45,
      availabilityScore: 70,
      overallViability: 58
    },
    dossier: {
      sections: {
        overview: 'The React Framework for the Web.',
        contributionRules: 'See CONTRIBUTING.md for detailed guidelines.',
        successPatterns: 'Include repro steps in bug fixes.',
        antiPatterns: 'Do not submit large PRs without an RFC.',
        issueBoard: 'Look for area: labels.',
        environmentSetup: 'pnpm install && pnpm build'
      }
    },
    meta: {
      stars: 120000,
      language: 'TypeScript',
      license: 'MIT',
      openIssueCount: 2300,
      hasContributing: true
    }
  }
]

export const mockOSSScoredIssues = [
  {
    id: 'github-acme-corp-widget-api-1234',
    repo: 'acme-corp/widget-api',
    number: 1234,
    title: 'Fix memory leak in request handler',
    url: 'https://github.com/acme-corp/widget-api/issues/1234',
    cvs: 92,
    cvsTier: 'go' as const,
    lifecycleStage: 'fresh',
    complexity: 'low',
    labels: ['good first issue', 'bug'],
    commentCount: 3,
    assignees: [],
    claimStatus: 'available',
    createdAt: new Date(Date.now() - 86400000).toISOString(),
    dataCompleteness: 'full' as const,
    repoKilled: false
  },
  {
    id: 'github-acme-corp-widget-api-5678',
    repo: 'acme-corp/widget-api',
    number: 5678,
    title: 'Add TypeScript generics to route handler',
    url: 'https://github.com/acme-corp/widget-api/issues/5678',
    cvs: 65,
    cvsTier: 'likely' as const,
    lifecycleStage: 'triaged',
    complexity: 'medium',
    labels: ['enhancement', 'typescript'],
    commentCount: 7,
    assignees: [],
    claimStatus: 'available',
    createdAt: new Date(Date.now() - 172800000).toISOString(),
    dataCompleteness: 'partial' as const,
    repoKilled: false
  },
  {
    id: 'github-vercel-next.js-9999',
    repo: 'vercel/next.js',
    number: 9999,
    title: 'Fix hydration warning in dev mode',
    url: 'https://github.com/vercel/next.js/issues/9999',
    cvs: 45,
    cvsTier: 'maybe' as const,
    lifecycleStage: 'stale',
    complexity: 'high',
    labels: ['bug', 'hydration'],
    commentCount: 15,
    assignees: [],
    claimStatus: 'available',
    createdAt: new Date(Date.now() - 604800000).toISOString(),
    dataCompleteness: 'full' as const,
    repoKilled: false
  }
]

export const mockOSSSubmittedPRs = [
  {
    originSlug: 'acme-corp/widget-api',
    prUrl: 'https://github.com/acme-corp/widget-api/pull/9876',
    prNumber: 9876,
    title: 'Fix memory leak in request handler',
    state: 'open',
    reviewDecision: null,
    comment_count: 3,
    labels: ['bug', 'good first issue'],
    submittedAt: new Date(Date.now() - 86400000).toISOString(),
    lastPolledAt: new Date(Date.now() - 600000).toISOString()
  },
  {
    originSlug: 'vercel/next.js',
    prUrl: 'https://github.com/vercel/next.js/pull/5555',
    prNumber: 5555,
    title: 'Fix hydration warning in dev mode',
    state: 'merged',
    reviewDecision: 'APPROVED',
    comment_count: 7,
    labels: ['hydration'],
    submittedAt: new Date(Date.now() - 172800000).toISOString(),
    lastPolledAt: new Date(Date.now() - 300000).toISOString()
  }
]

// Pipeline assignment mock data for Tab 3 (Pipeline Runs)
export const mockPipelineStatuses = [
  {
    originSlug: 'acme-corp/widget-api',
    repo: 'widget-api',
    issueNumber: 1234,
    forkIssueNumber: 1,
    forkIssueUrl: 'https://github.com/test-user/widget-api/issues/1',
    assignedAt: new Date(Date.now() - 7200000).toISOString(),
    stage4Status: 'retrospective_complete',
    stage4PrNumber: 10,
    stage4PrBranch: 'fix/memory-leak',
    stage4ReviewRequested: true,
    stage4SweDoneAt: new Date(Date.now() - 5400000).toISOString(),
    stage4SaRunId: 'sa-run-1',
    stage4SaDoneAt: new Date(Date.now() - 3600000).toISOString(),
    stage4ReviewDoneAt: new Date(Date.now() - 1800000).toISOString(),
    stage4RemediationDoneAt: new Date(Date.now() - 900000).toISOString(),
    language: 'JavaScript',
    contextTier: 'full',
    dossierCompleteness: 1.0
  },
  {
    originSlug: 'vercel/next.js',
    repo: 'next.js',
    issueNumber: 9999,
    forkIssueNumber: 2,
    forkIssueUrl: 'https://github.com/test-user/next.js/issues/2',
    assignedAt: new Date(Date.now() - 3600000).toISOString(),
    stage4Status: 'static_analysis_running',
    stage4PrNumber: null,
    stage4PrBranch: null,
    stage4ReviewRequested: false,
    stage4SweDoneAt: new Date(Date.now() - 1800000).toISOString(),
    stage4SaRunId: null,
    stage4SaDoneAt: null,
    stage4ReviewDoneAt: null,
    stage4RemediationDoneAt: null,
    language: 'TypeScript',
    contextTier: 'partial',
    dossierCompleteness: 0.8
  }
]

export const mockRetrospectiveLogs = [
  {
    repo: 'widget-api',
    issue_number: 1234,
    timestamp: new Date(Date.now() - 900000).toISOString(),
    swe: { reproduced: true, verified: true, tool_installed: true },
    static_analysis: { ran: true, passed: true },
    review: { requested: true, decision: 'approved' },
    remediation: { ran: true, fixes_applied: 2 },
    workflow: { compliant: true },
    timing: { total_seconds: 3600 },
    data_quality: { completeness: 1.0 },
    pipeline: { status: 'retrospective_complete' }
  }
]

export const mockOSSIssueBrief = {
  issue: {
    id: 'github-acme-corp-widget-api-1234',
    number: 1234,
    title: 'Fix memory leak in request handler',
    cvs: 92,
    cvsTier: 'go' as const
  },
  repoHealth: {
    maintainerHealthScore: 85,
    mergeAccessibilityScore: 72,
    availabilityScore: 90,
    overallViability: 82
  },
  brief:
    '## Contribution Brief\n\nThis issue involves fixing a memory leak in the request handler.\n\n### Key Points\n- Focus on the `onRequest` hook lifecycle\n- Add cleanup in `onResponse`\n- Follow widget-api patterns'
}

// ============ Retrospective Batch Mock Data ============

export const mockRetroBatches = [
  {
    batch_id: 'crimson-kitty',
    created_at: new Date(Date.now() - 86400000).toISOString(),
    note: 'Active batch — Mar 24 2026',
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
    note: '55-issue run Mar 13–17 2026',
    issue_count: 55,
    upstream_pr_count: 28,
    upstream_merged: 3,
    upstream_closed: 5,
    upstream_open: 20,
    has_fork_pr: 40
  }
]

export const mockRetroBatchDetail = {
  batch: mockRetroBatches[0],
  issues: [
    {
      assignment: {
        origin_slug: 'acme-corp/widget-api',
        issue_number: 1234,
        assigned_at: new Date(Date.now() - 7200000).toISOString(),
        stage4_pr_number: 10,
        context_tier: 1,
        batch_id: 'crimson-kitty'
      },
      upstream_pr: {
        pr_url: 'https://github.com/acme-corp/widget-api/pull/9876',
        pr_number: 9876,
        title: 'Fix memory leak in request handler',
        state: 'merged',
        submitted_at: new Date(Date.now() - 3600000).toISOString(),
        merged_at: new Date(Date.now() - 1800000).toISOString(),
        issue_number: 1234
      },
      retro: {
        origin_slug: 'acme-corp/widget-api',
        issue_number: 1234,
        batch_id: 'crimson-kitty',
        timing: {
          assigned_at: new Date(Date.now() - 7200000).toISOString(),
          swe_done_at: new Date(Date.now() - 5400000).toISOString(),
          sa_done_at: new Date(Date.now() - 3600000).toISOString(),
          review_done_at: new Date(Date.now() - 1800000).toISOString(),
          remediation_done_at: new Date(Date.now() - 900000).toISOString()
        },
        workflow: {
          reproduced: true,
          verified: true,
          self_corrected: false,
          code_review: true,
          step_count: 15,
          tools_used: ['bash', 'editor']
        },
        static_analysis: {
          conclusion: 'success',
          jobs: [
            {
              name: 'lint',
              conclusion: 'success',
              annotations: [
                {
                  path: 'src/request.js',
                  line: 42,
                  level: 'warning',
                  message: 'Unused variable'
                }
              ]
            }
          ]
        },
        context_issue_body: '## Context\n\nThis is the fork issue context brief.',
        upstream_pr_body: '## Summary\n\nFixes memory leak in request handler.',
        raw_comments: {
          fork_pr: [
            {
              author: 'hadoku',
              body: 'Looks good to me, nice fix!',
              created_at: new Date(Date.now() - 4000000).toISOString(),
              comment_type: 'regular'
            },
            {
              author: 'copilot-swe-agent',
              body: 'I have fixed the issue as requested.',
              created_at: new Date(Date.now() - 4200000).toISOString(),
              comment_type: 'regular'
            },
            {
              author: 'hadoku',
              body: 'This line looks off.',
              created_at: new Date(Date.now() - 3800000).toISOString(),
              comment_type: 'inline',
              path: 'src/request.js',
              line: 55
            }
          ],
          upstream_pr: [
            {
              author: 'upstream-maintainer',
              body: 'Thanks for the contribution, merging!',
              created_at: new Date(Date.now() - 1500000).toISOString(),
              comment_type: 'regular'
            },
            {
              author: 'github-actions[bot]',
              body: 'CI passed.',
              created_at: new Date(Date.now() - 2000000).toISOString(),
              comment_type: 'regular'
            }
          ]
        }
      }
    },
    {
      assignment: {
        origin_slug: 'vercel/next.js',
        issue_number: 9999,
        assigned_at: new Date(Date.now() - 86400000).toISOString(),
        stage4_pr_number: null,
        context_tier: 3,
        batch_id: 'crimson-kitty'
      },
      upstream_pr: null,
      retro: {
        origin_slug: 'vercel/next.js',
        issue_number: 9999,
        batch_id: 'crimson-kitty'
        // no timing — pre-telemetry
      }
    }
  ]
}

// ============ Task automation ============

export const mockTaskAutoPRs = [
  {
    repo: 'WolffM/hadoku-task',
    number: 72,
    title: 'fix dragging in edit boards view',
    url: 'https://github.com/WolffM/hadoku-task/pull/72',
    branch: 'taskauto/ms3gt4qmq0xi',
    taskId: 'MS3GT4QMQ0XISM3R1IZFF34BU2',
    additions: 25,
    deletions: 5,
    changedFiles: 2,
    mergeState: 'CLEAN',
    isDraft: false,
    checks: 'passing',
    updatedAt: '2026-07-28T01:52:51Z'
  },
  {
    repo: 'WolffM/hadoku-task',
    number: 73,
    title: 'make coffee theme default',
    url: 'https://github.com/WolffM/hadoku-task/pull/73',
    branch: 'taskauto/ms3k7f81as2a',
    taskId: 'MS3K7F81AS2A6471SS20L34OVC',
    additions: 4,
    deletions: 1,
    changedFiles: 1,
    mergeState: 'CLEAN',
    isDraft: false,
    checks: 'passing',
    updatedAt: '2026-07-28T02:10:00Z'
  }
]

export const mockTaskAutoStatus = {
  success: true,
  boards: [
    {
      handle: 'MS0Y0VKGSIQNB5Y1P4S805OQP3',
      name: 'task',
      repo: 'WolffM/hadoku-task',
      lanes: {
        'plan-review': [
          {
            id: 'MS3K7F81AS2A6471SS20L34OVC',
            title: 'a couple of quality of life features',
            claimed: false,
            updatedAt: '2026-07-27T18:55:00Z',
            hasPlan: true,
            stuck: false
          }
        ],
        landed: [
          {
            id: 'MS3GT4QMQ0XISM3R1IZFF34BU2',
            title: 'buggy interaction with dragging while in edit boards view',
            claimed: false,
            updatedAt: '2026-07-28T01:52:52Z',
            hasPlan: true,
            stuck: false
          }
        ]
      },
      counts: { 'plan-review': 1, landed: 1 },
      prs: mockTaskAutoPRs
    }
  ],
  running: [],
  laneOrder: [
    '(inbox)',
    'planning',
    'plan-review',
    'replan',
    'approved',
    'working',
    'landing',
    'landed',
    'stalled'
  ],
  prCount: 2
}

export const mockTaskAutoDetail = {
  success: true,
  board: {
    handle: 'MS0Y0VKGSIQNB5Y1P4S805OQP3',
    name: 'task',
    repo: 'WolffM/hadoku-task'
  },
  task: {
    id: 'MS3GT4QMQ0XISM3R1IZFF34BU2',
    title: 'buggy interaction with dragging while in edit boards view',
    notes:
      '## What I think you want\n\nDragging misbehaves in edit mode.\n\n## Plan\n\n1. fix the drag handler\n',
    lane: 'landed',
    laneTags: ['landed'],
    tag: 'landed',
    claimed: false,
    state: 'Active',
    createdAt: '2026-07-27T18:36:54Z',
    updatedAt: '2026-07-28T01:52:52Z',
    branch: 'taskauto/ms3gt4qmq0xi',
    metrics: { agent_s: 210.467, implement_s: 210.467, implement_runs: 1 }
  },
  history: [
    {
      agentId: 'a1',
      claimedAt: '2026-07-27T19:12:22Z',
      endedAt: '2026-07-27T19:15:05Z',
      endedBy: 'release',
      outcome: 'plan:ready'
    },
    {
      agentId: 'a1',
      claimedAt: '2026-07-28T01:41:20Z',
      endedAt: '2026-07-28T01:52:52Z',
      endedBy: 'release',
      outcome: 'pr-open:72'
    }
  ],
  prs: [{ ...mockTaskAutoPRs[0], state: 'OPEN', mergedAt: '', createdAt: '2026-07-28T01:52:51Z' }]
}

declare global {
  interface Window {
    __taskautoMerges?: { repo: string; number: number; auto?: boolean }[]
  }
}

// ============ Temporal ============

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
