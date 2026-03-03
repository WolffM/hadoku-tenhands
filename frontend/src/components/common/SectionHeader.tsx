/**
 * SectionHeader Component
 *
 * Renders the stage-section__header block with icon, title, count,
 * and optional action buttons passed as children.
 */

import type { ReactNode } from 'react'

interface SectionHeaderProps {
  icon?: string
  title: string
  count?: number
  children?: ReactNode
}

export function SectionHeader({ icon, title, count, children }: SectionHeaderProps) {
  return (
    <div className="stage-section__header">
      <h3 className="stage-section__title">
        {icon && <span className="stage-section__icon">{icon}</span>}
        {title}
        {count !== undefined && ` (${count})`}
      </h3>
      {children && <div className="stage-section__actions">{children}</div>}
    </div>
  )
}
