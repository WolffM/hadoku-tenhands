interface LoadingStateProps {
  text: string
}

export function LoadingState({ text }: LoadingStateProps) {
  return (
    <div className="loading-state">
      <div className="loading-state__spinner" />
      <p className="loading-state__text">{text}</p>
    </div>
  )
}
