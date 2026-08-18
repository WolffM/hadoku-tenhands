/**
 * Severity Utilities
 */

import type { Issue, Label, SeverityLevel } from '../api/types'

/**
 * Extract severity level from an issue
 */
export function getSeverity(issue: Issue): SeverityLevel {
  return getSeverityFromLabels(issue.labels)
}

/**
 * Extract severity level from labels
 */
function getSeverityFromLabels(labels: Label[]): SeverityLevel {
  const labelNames = labels.map(l => l.name.toLowerCase())

  if (labelNames.some(l => l.includes('severity:critical'))) return 'critical'
  if (labelNames.some(l => l.includes('severity:high'))) return 'high'
  if (labelNames.some(l => l.includes('severity:medium'))) return 'medium'
  if (labelNames.some(l => l.includes('severity:low'))) return 'low'

  return 'unknown'
}

/**
 * Get CSS class for severity level
 */
export function getSeverityClass(severity: SeverityLevel): string {
  switch (severity) {
    case 'critical':
      return 'severity-critical'
    case 'high':
      return 'severity-high'
    case 'medium':
      return 'severity-medium'
    case 'low':
      return 'severity-low'
    default:
      return 'severity-unknown'
  }
}
