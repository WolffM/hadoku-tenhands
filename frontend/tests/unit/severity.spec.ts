import { test, expect } from '@playwright/test'

import { getSeverity, getSeverityClass } from '../../src/utils/severity'
import type { Issue, SeverityLevel } from '../../src/api/types'

function issueWith(...labelNames: string[]): Issue {
  return {
    number: 1,
    title: 'test issue',
    state: 'open',
    url: 'https://example.invalid/1',
    createdAt: '2026-01-01T00:00:00Z',
    labels: labelNames.map(name => ({ name })),
    assignees: []
  }
}

test('reads the severity level off a severity: label', () => {
  expect(getSeverity(issueWith('severity:critical'))).toBe('critical')
  expect(getSeverity(issueWith('severity:high'))).toBe('high')
  expect(getSeverity(issueWith('severity:medium'))).toBe('medium')
  expect(getSeverity(issueWith('severity:low'))).toBe('low')
})

test('matches the label case-insensitively and as a substring', () => {
  expect(getSeverity(issueWith('Severity:High'))).toBe('high')
  expect(getSeverity(issueWith('triage/severity:medium (needs review)'))).toBe('medium')
})

test('the most severe label present wins, whatever the label order', () => {
  expect(getSeverity(issueWith('severity:low', 'severity:critical'))).toBe('critical')
  expect(getSeverity(issueWith('severity:critical', 'severity:low'))).toBe('critical')
  expect(getSeverity(issueWith('severity:medium', 'severity:high'))).toBe('high')
})

test('falls back to unknown with no severity label at all', () => {
  expect(getSeverity(issueWith())).toBe('unknown')
  expect(getSeverity(issueWith('bug', 'good first issue'))).toBe('unknown')
})

test('a bare "critical" label is not a severity label', () => {
  // The match is on the `severity:` prefix, not the word — a label named
  // "critical" alone stays unknown. Pinned because widening this predicate
  // would silently re-rank every issue in the queue.
  expect(getSeverity(issueWith('critical'))).toBe('unknown')
})

test('every severity level maps to its own CSS class', () => {
  const levels: SeverityLevel[] = ['critical', 'high', 'medium', 'low', 'unknown']
  expect(levels.map(getSeverityClass)).toEqual([
    'severity-critical',
    'severity-high',
    'severity-medium',
    'severity-low',
    'severity-unknown'
  ])
})
