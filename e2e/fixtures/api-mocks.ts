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
  author: { login: 'copilot[bot]' },
  createdAt: new Date(Date.now() - 3600000).toISOString(),
  headRefName: 'fix/auth-security',
  baseRefName: 'main',
  files: [
    { path: 'src/auth/validator.ts', additions: 30, deletions: 5 },
    { path: 'src/auth/handler.ts', additions: 10, deletions: 5 },
    { path: 'tests/auth.test.ts', additions: 5, deletions: 2 }
  ],
  commits: [{ message: 'Add input validation to auth module' }],
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

// ============ Mock Setup Functions ============

/**
 * Set up all API mocks for a page
 */
export async function mockAllAPIs(page: Page): Promise<void> {
  await mockOwnerAPI(page)
  await mockStageAPIs(page)
  await mockHealthAPIs(page)
  await mockActionAPIs(page)
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
