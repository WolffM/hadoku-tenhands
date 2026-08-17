import './demo.css'

const REPO_URL = 'https://github.com/WolffM/hadoku-tenhands'

/**
 * A fixed banner that makes the fiction explicit: every view is real, the data
 * is a static fixture corpus, and write actions only mutate local state.
 */
export function DemoBadge() {
  return (
    <div className="demo-badge" role="note" aria-label="Demo notice">
      <span className="demo-badge__dot" aria-hidden="true" />
      <span className="demo-badge__text">
        <span className="demo-badge__strong">Demo</span> — static fixture data. The live pipeline
        runs behind auth at hadoku.me.
      </span>
      <a className="demo-badge__link" href={REPO_URL} target="_blank" rel="noreferrer noopener">
        Repo ↗
      </a>
    </div>
  )
}
