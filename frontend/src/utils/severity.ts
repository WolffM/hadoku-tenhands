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
export function getSeverityFromLabels(labels: Label[]): SeverityLevel {
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

/**
 * Get color for severity level (for inline styles)
 */
export function getSeverityColor(severity: SeverityLevel): string {
  switch (severity) {
    case 'critical':
      return 'var(--color-error, #dc3545)'
    case 'high':
      return 'var(--color-warning, #fd7e14)'
    case 'medium':
      return 'var(--color-info, #0dcaf0)'
    case 'low':
      return 'var(--color-success, #198754)'
    default:
      return 'var(--color-text-secondary, #6c757d)'
  }
}

/**
 * Get display label for severity level
 */
export function getSeverityLabel(severity: SeverityLevel): string {
  switch (severity) {
    case 'critical':
      return 'Critical'
    case 'high':
      return 'High'
    case 'medium':
      return 'Medium'
    case 'low':
      return 'Low'
    default:
      return 'Unknown'
  }
}
