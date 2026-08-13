interface EmptyStateProps {
  icon: string
  title: string
  description?: string
  /** Optional data-testid so callers keep their spec hooks. */
  testId?: string
}

export function EmptyState({ icon, title, description, testId }: EmptyStateProps) {
  return (
    <div className="empty-state" data-testid={testId}>
      <div className="empty-state__icon">{icon}</div>
      <h3 className="empty-state__title">{title}</h3>
      {description && <p className="empty-state__description">{description}</p>}
    </div>
  )
}
