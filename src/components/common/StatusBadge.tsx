/**
 * StatusBadge Component
 *
 * Displays a status indicator badge.
 */

import type { PipelineStatus } from '../../api/types'

interface StatusBadgeProps {
  status: PipelineStatus
  size?: 'sm' | 'md' | 'lg'
}

const statusConfig: Record<PipelineStatus, { label: string; className: string }> = {
  pending: { label: 'Pending', className: 'status-pending' },
  processing: { label: 'Processing', className: 'status-processing' },
  waiting_for_review: { label: 'Waiting', className: 'status-waiting' },
  ready: { label: 'Ready', className: 'status-ready' },
  completed: { label: 'Completed', className: 'status-completed' },
  failed: { label: 'Failed', className: 'status-failed' }
}

export function StatusBadge({ status, size = 'md' }: StatusBadgeProps) {
  const config = statusConfig[status]

  return (
    <span className={`status-badge status-badge-${size} ${config.className}`} title={config.label}>
      {config.label}
    </span>
  )
}
