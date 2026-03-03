/**
 * Badge Component
 *
 * Generic colored badge using the badge--{variant} CSS classes.
 * Replaces duplicated inline badge rendering across panels.
 */

import type { ReactNode } from 'react'

export type BadgeVariant = 'primary' | 'secondary' | 'success' | 'warning' | 'danger' | 'info'

interface BadgeProps {
  children: ReactNode
  variant: BadgeVariant
}

export function Badge({ children, variant }: BadgeProps) {
  return <span className={`badge badge--${variant}`}>{children}</span>
}

/* ── Domain-specific variant maps ───────────────────────────────── */

/** GitHub workflow status → badge variant */
export const WORKFLOW_STATUS_VARIANT: Record<string, BadgeVariant> = {
  success: 'success',
  failure: 'danger',
  in_progress: 'info',
  queued: 'info',
  triggered: 'info'
}

/** Pipeline Stage4Status → badge variant */
export function getStage4BadgeVariant(status: string): BadgeVariant {
  if (status === 'retrospective_complete') return 'success'
  if (status.includes('running') || status.includes('working') || status.includes('in_progress'))
    return 'primary'
  if (status.includes('done') || status.includes('complete')) return 'warning'
  return 'secondary'
}

/** Submitted PR state/reviewDecision → badge variant + label */
export function getSubmittedPRBadge(pr: { state: string; reviewDecision?: string | null }): {
  variant: BadgeVariant
  label: string
} {
  if (pr.state === 'merged') return { variant: 'success', label: 'Merged' }
  if (pr.state === 'closed') return { variant: 'danger', label: 'Closed' }
  if (pr.reviewDecision === 'APPROVED') return { variant: 'success', label: 'Approved' }
  if (pr.reviewDecision === 'CHANGES_REQUESTED')
    return { variant: 'warning', label: 'Changes Requested' }
  return { variant: 'primary', label: 'Open' }
}

/** CVS tier → badge variant */
export const CVS_TIER_VARIANT: Record<string, BadgeVariant> = {
  go: 'success',
  likely: 'primary',
  maybe: 'warning',
  risky: 'danger',
  skip: 'secondary'
}

/** Health score → badge variant */
export function getHealthBadgeVariant(score: number): BadgeVariant {
  if (score > 70) return 'success'
  if (score >= 40) return 'warning'
  return 'danger'
}
