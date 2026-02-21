/**
 * API Mock Helpers for Playwright Tests
 *
 * Intercepts Flask API calls and returns mock data for consistent testing.
 */

import type { Page } from '@playwright/test'

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
    slug: 'fastify-fastify',
    health: {
      maintainerHealthScore: 85,
      mergeAccessibilityScore: 72,
      availabilityScore: 90,
      overallViability: 82
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
    id: 'github-fastify-fastify-1234',
    repo: 'fastify/fastify',
    number: 1234,
    title: 'Fix memory leak in request handler',
    url: 'https://github.com/fastify/fastify/issues/1234',
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
    id: 'github-fastify-fastify-5678',
    repo: 'fastify/fastify',
    number: 5678,
    title: 'Add TypeScript generics to route handler',
    url: 'https://github.com/fastify/fastify/issues/5678',
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

export const mockOSSAssignments = [
  {
    originSlug: 'fastify/fastify',
    repo: 'fastify',
    issueNumber: 1234,
    forkIssueNumber: 1,
    forkIssueUrl: 'https://github.com/test-user/fastify/issues/1',
    assignedAt: new Date(Date.now() - 3600000).toISOString()
  }
]

export const mockOSSForkPRs = [
  {
    number: 1,
    title: 'Fix memory leak in request handler',
    url: 'https://github.com/test-user/fastify/pull/1',
    repo: 'fastify',
    originSlug: 'fastify/fastify',
    headRefName: 'fix/memory-leak',
    additions: 25,
    deletions: 8,
    changedFiles: 3,
    reviewDecision: '',
    isDraft: false,
    createdAt: new Date(Date.now() - 1800000).toISOString()
  },
  {
    number: 2,
    title: '[WIP] Add TypeScript generics',
    url: 'https://github.com/test-user/fastify/pull/2',
    repo: 'fastify',
    originSlug: 'fastify/fastify',
    headRefName: 'feat/ts-generics',
    additions: 50,
    deletions: 0,
    changedFiles: 2,
    reviewDecision: '',
    isDraft: true,
    createdAt: new Date(Date.now() - 7200000).toISOString()
  }
]

export const mockOSSForkPRDetails = {
  number: 1,
  title: 'Fix memory leak in request handler',
  body: 'This PR fixes the memory leak described in fastify/fastify#1234.',
  author: { login: 'copilot[bot]' },
  createdAt: new Date(Date.now() - 1800000).toISOString(),
  headRefName: 'fix/memory-leak',
  baseRefName: 'main',
  repo: 'fastify',
  files: [
    { path: 'lib/request.js', additions: 15, deletions: 5 },
    { path: 'lib/handler.js', additions: 8, deletions: 3 },
    { path: 'test/request.test.js', additions: 2, deletions: 0 }
  ],
  commits: 1,
  reviewDecision: null,
  state: 'open',
  url: 'https://github.com/test-user/fastify/pull/1',
  isDraft: false,
  additions: 25,
  deletions: 8,
  changedFiles: 3,
  diff: `diff --git a/lib/request.js b/lib/request.js
index abc123..def456 100644
--- a/lib/request.js
+++ b/lib/request.js
@@ -10,5 +10,15 @@
+  // Fix: clear reference to prevent memory leak
+  request.data = null`
}

export const mockOSSReadyToSubmit = [
  {
    originSlug: 'fastify/fastify',
    repo: 'fastify',
    branch: 'fix/memory-leak',
    title: 'Fix memory leak in request handler',
    baseBranch: 'main'
  }
]

export const mockOSSSubmittedPRs = [
  {
    originSlug: 'fastify/fastify',
    prUrl: 'https://github.com/fastify/fastify/pull/9876',
    prNumber: 9876,
    title: 'Fix memory leak in request handler',
    state: 'open',
    submittedAt: new Date(Date.now() - 86400000).toISOString(),
    lastPolledAt: new Date(Date.now() - 600000).toISOString()
  }
]

// ============ Mock Setup Functions ============

/**
 * Set up all API mocks for a page (vibecheck + OSS + health)
 */
export async function mockAllAPIs(page: Page): Promise<void> {
  await mockOwnerAPI(page)
  await mockStageAPIs(page)
  await mockHealthAPIs(page)
  await mockActionAPIs(page)
  await mockOSSAPIs(page)
}

/**
 * Mock the owner endpoint
 */
export async function mockOwnerAPI(page: Page): Promise<void> {
  await page.route('**/dispatch/api/owner', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, owner: mockOwner })
    })
  })
}

/**
 * Mock all stage data endpoints
 */
export async function mockStageAPIs(page: Page): Promise<void> {
  await page.route('**/dispatch/api/stage1-repos', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        owner: mockOwner,
        repos: mockStage1Repos
      })
    })
  })

  await page.route('**/dispatch/api/stage2-repos', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        owner: mockOwner,
        repos: mockStage2Repos
      })
    })
  })

  await page.route('**/dispatch/api/stage3-issues', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        owner: mockOwner,
        issues: mockStage3Issues,
        labels: [
          'vibeCheck',
          'severity:critical',
          'severity:high',
          'severity:medium',
          'severity:low'
        ],
        repos_with_copilot_prs: []
      })
    })
  })

  await page.route('**/dispatch/api/stage4-prs', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        owner: mockOwner,
        prs: mockStage4PRs
      })
    })
  })

  await page.route('**/dispatch/api/pr-details', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        pr: mockPRDetails
      })
    })
  })
}

/**
 * Mock health check endpoints
 */
export async function mockHealthAPIs(page: Page): Promise<void> {
  await page.route('**/dispatch/api/healthcheck', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        status: 'healthy',
        owner: mockOwner,
        api_version: '2.0.0'
      })
    })
  })

  await page.route('**/dispatch/api/global-workflow-runs', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        runs: mockWorkflowRuns,
        owner: mockOwner
      })
    })
  })
}

/**
 * Mock action endpoints (install, run, assign, approve, merge)
 */
export async function mockActionAPIs(page: Page): Promise<void> {
  await page.route('**/dispatch/api/install-vibecheck', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'vibeCheck workflow installed!'
      })
    })
  })

  await page.route('**/dispatch/api/run-vibecheck', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'vibeCheck workflow triggered!'
      })
    })
  })

  await page.route('**/dispatch/api/assign-copilot', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'Copilot assigned!'
      })
    })
  })

  await page.route('**/dispatch/api/approve-pr', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'PR approved!'
      })
    })
  })

  await page.route('**/dispatch/api/mark-pr-ready', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'PR marked as ready!'
      })
    })
  })

  await page.route('**/dispatch/api/merge-pr', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        message: 'PR merged!'
      })
    })
  })
}

/**
 * Mock all OSS pipeline endpoints
 */
export async function mockOSSAPIs(page: Page): Promise<void> {
  // Stage endpoints
  await page.route('**/dispatch/api/oss/stage1-targets', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, targets: mockOSSTargets, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/stage2-issues', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, issues: mockOSSScoredIssues, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/stage3-assigned', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, assignments: mockOSSAssignments, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/stage4-fork-prs', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, prs: mockOSSForkPRs, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/stage5-submit', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, ready: mockOSSReadyToSubmit, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/stage5-tracking', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, submitted: mockOSSSubmittedPRs, owner: mockOwner })
    })
  })

  // Detail endpoints
  await page.route('**/dispatch/api/oss/fork-pr-details', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, pr: mockOSSForkPRDetails, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/dossier/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        dossier: {
          slug: 'fastify-fastify',
          generatedAt: new Date().toISOString(),
          sections: {
            overview: 'Popular Node.js framework for building web applications.',
            contributionRules: 'Follow the style guide and add tests.',
            successPatterns: 'Small focused PRs with clear descriptions.',
            antiPatterns: 'Avoid large refactors without prior discussion.',
            issueBoard: 'Check the good first issue label.',
            environmentSetup: 'Run npm install && npm test.'
          }
        },
        owner: mockOwner
      })
    })
  })

  await page.route('**/dispatch/api/oss/poll-submitted-prs', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, submitted: mockOSSSubmittedPRs, owner: mockOwner })
    })
  })

  // Action endpoints
  await page.route('**/dispatch/api/oss/add-target', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Target added!', owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/remove-target', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'Target removed!', owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/refresh-target', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/select-issue', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/fork-and-assign', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        fork_issue_url: 'https://github.com/test-user/fastify/issues/2',
        fork_issue_number: 2,
        owner: mockOwner
      })
    })
  })

  await page.route('**/dispatch/api/oss/approve-fork-pr', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'PR approved!', owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/merge-fork-pr', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, message: 'PR merged!', owner: mockOwner })
    })
  })

  await page.route('**/dispatch/api/oss/submit-to-origin', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        pr_url: 'https://github.com/fastify/fastify/pull/5555',
        owner: mockOwner
      })
    })
  })
}
