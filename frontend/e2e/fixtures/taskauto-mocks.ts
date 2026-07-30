/**
 * Task Automation API mocks.
 *
 * The status endpoint deliberately keeps listing a PR after it is merged.
 * That is what the real backend does — it re-reads GitHub on the next poll,
 * and `gh` takes a moment to agree — and it is exactly the lag that used to
 * make a merged row come back with a live Merge button before disappearing.
 */

import type { Page } from '@playwright/test'

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
    __taskautoMerges?: { repo: string; number: number }[]
  }
}

export async function mockTaskAutoAPIs(page: Page) {
  await page.route('**/tenhands/api/taskauto/status', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockTaskAutoStatus)
    })
  })

  await page.route('**/tenhands/api/taskauto/task/**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockTaskAutoDetail)
    })
  })

  await page.route('**/tenhands/api/taskauto/merge', async route => {
    const body = route.request().postDataJSON() as { repo: string; number: number }
    await page.evaluate(merge => {
      window.__taskautoMerges = [...(window.__taskautoMerges ?? []), merge]
    }, body)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, ...body })
    })
  })
}
