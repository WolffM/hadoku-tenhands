interface LoadingStateProps {
  text: string
  /** Optional data-testid so callers keep their spec hooks. */
  testId?: string
}

export function LoadingState({ text, testId }: LoadingStateProps) {
  return (
    <div className="loading-state" data-testid={testId}>
      <div className="loading-state__spinner" />
      <p className="loading-state__text">{text}</p>
    </div>
  )
}
