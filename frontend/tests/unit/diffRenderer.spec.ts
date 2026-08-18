import { test, expect } from '@playwright/test'

import { renderDiffToHtml, getDiffStats } from '../../src/utils/diffRenderer'

const GIT_DIFF = [
  'diff --git a/src/app.ts b/src/app.ts',
  'index 1111111..2222222 100644',
  '--- a/src/app.ts',
  '+++ b/src/app.ts',
  '@@ -10,3 +10,4 @@ export function run() {',
  ' const before = 1',
  '-const removed = 2',
  '+const added = 2',
  '+const alsoAdded = 3',
  ' const after = 4'
].join('\n')

test('counts additions and deletions per file', () => {
  expect(getDiffStats(GIT_DIFF)).toEqual({ files: 1, additions: 2, deletions: 1 })
})

test('sums stats across every file in a multi-file diff', () => {
  const twoFiles = [
    GIT_DIFF,
    'diff --git a/src/other.ts b/src/other.ts',
    '@@ -1,2 +1,1 @@',
    '-gone',
    '-alsoGone',
    '+replacement'
  ].join('\n')

  // 2+1 additions and 1+2 deletions — the totals are repo-wide, not per-file.
  expect(getDiffStats(twoFiles)).toEqual({ files: 2, additions: 3, deletions: 3 })
})

test('a bare unified diff with no `diff --git` header still counts as a file', () => {
  // Regression pin: hunk-only diffs used to fall through the `!currentFile`
  // guard entirely and render as "No changes".
  const bare = ['--- a/src/app.ts', '+++ b/src/app.ts', '@@ -1 +1 @@', '-old', '+new'].join('\n')

  expect(getDiffStats(bare)).toEqual({ files: 1, additions: 1, deletions: 1 })
  expect(renderDiffToHtml(bare)).toContain('src/app.ts')
})

test('an empty or unparseable diff renders the empty state', () => {
  expect(renderDiffToHtml('')).toBe('<div class="diff-empty">No changes</div>')
  expect(renderDiffToHtml('not a diff at all')).toBe('<div class="diff-empty">No changes</div>')
  expect(getDiffStats('')).toEqual({ files: 0, additions: 0, deletions: 0 })
})

test('renders the filename, the stats header, and one row per line', () => {
  const html = renderDiffToHtml(GIT_DIFF)

  expect(html).toContain('<span class="diff-filename">src/app.ts</span>')
  expect(html).toContain('<span class="diff-additions">+2</span>')
  expect(html).toContain('<span class="diff-deletions">-1</span>')
  expect(html).toContain('diff-line-addition')
  expect(html).toContain('diff-line-deletion')
  expect(html).toContain('diff-line-hunk')
})

test('numbers old and new lines independently across a hunk', () => {
  const html = renderDiffToHtml(GIT_DIFF)
  const rows = [
    ...html.matchAll(
      /<tr class="diff-line diff-line-(addition|deletion|context)">.*?<td class="diff-line-num diff-line-num-old">(\d*)<\/td><td class="diff-line-num diff-line-num-new">(\d*)<\/td>/g
    )
  ]

  expect(rows.map(m => [m[1], m[2], m[3]])).toEqual([
    ['context', '10', '10'],
    ['deletion', '11', ''],
    ['addition', '', '11'],
    ['addition', '', '12'],
    ['context', '12', '13']
  ])
})

test('escapes diff content so a patch cannot inject markup', () => {
  const hostile = [
    'diff --git a/x.html b/x.html',
    '@@ -1 +1 @@',
    '+<script>alert("xss")</script>'
  ].join('\n')

  const html = renderDiffToHtml(hostile)
  expect(html).not.toContain('<script>')
  expect(html).toContain('&lt;script&gt;')
})
