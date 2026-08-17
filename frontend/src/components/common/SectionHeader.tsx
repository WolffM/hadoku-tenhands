/**
 * SectionHeader Component
 *
 * Renders the stage-section__header block with icon, title, count,
 * and optional action buttons passed as children.
 */

import type { ReactElement, ReactNode } from 'react'
import { Icon, type IconName } from '@wolffm/themes'

interface SectionHeaderProps {
  /**
   * A registry name (`"star"`) or a built element (`<Icon name="star" />`).
   * Deliberately NOT `ReactNode`: that accepted any string, so the icon
   * migration's `icon="star"` typechecked and rendered the word "star".
   */
  icon?: IconName | ReactElement
  title: string
  count?: number
  children?: ReactNode
}

export function SectionHeader({ icon, title, count, children }: SectionHeaderProps) {
  return (
    <div className="stage-section__header">
      <h3 className="stage-section__title">
        {icon && (
          <span className="stage-section__icon">
            {typeof icon === 'string' ? <Icon name={icon} /> : icon}
          </span>
        )}
        {title}
        {count !== undefined && ` (${count})`}
      </h3>
      {children && <div className="stage-section__actions">{children}</div>}
    </div>
  )
}
