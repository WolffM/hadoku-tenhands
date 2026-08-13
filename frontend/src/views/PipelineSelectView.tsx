/**
 * PipelineSelectView
 *
 * Landing view for selecting which pipeline to use.
 * Renders horizontal row cards for each available pipeline.
 */

import { usePipelineStore } from '../store'

const pipelines = [
  {
    id: 'list' as const,
    title: 'Vibecheck Pipeline',
    era: 'Gen 1 · Vibecheck',
    description: 'Install, run, assign, and review vibecheck across your repos',
    stages: ['Install VibeCheck', 'Run VibeCheck', 'Assign Copilot', 'Review & Merge'],
    icon: '🔍'
  },
  {
    id: 'oss' as const,
    title: 'OSS Contribution Pipeline',
    era: 'Gen 2 · OSS Recon',
    description: 'Repo health, issue selection, pipeline runs, upstream review',
    stages: ['Repo Health', 'Fork & Assign', 'Pipeline Runs', 'Review'],
    icon: '🌐'
  },
  {
    id: 'temporal' as const,
    title: 'Crimson-Kitty (Temporal)',
    era: 'Gen 3 · Crimson-Kitty',
    description:
      'Contributions that show their work: every step leaves evidence, and you approve from an inbox',
    stages: ['Inbox', 'Active', 'Archive'],
    icon: '🐈'
  },
  {
    id: 'taskauto' as const,
    title: 'Task Automation',
    era: 'Gen 4 · Task Automation',
    description:
      'Board-driven: a task typed on a phone becomes a plan you approve, then a pull request you merge',
    stages: ['Review', 'Boards'],
    icon: '📋'
  }
]

export function PipelineSelectView() {
  const setActiveView = usePipelineStore(state => state.setActiveView)

  return (
    <div className="pipeline-select">
      <div className="pipeline-select__header">
        <h2 className="pipeline-select__title">Select a Pipeline</h2>
      </div>
      <div className="pipeline-select__list">
        {pipelines.map(pipeline => (
          <button
            key={pipeline.id}
            className="pipeline-select-card"
            onClick={() => setActiveView(pipeline.id)}
          >
            <div className="pipeline-select-card__icon">{pipeline.icon}</div>
            <div className="pipeline-select-card__content">
              <div className="pipeline-select-card__heading">
                <h3 className="pipeline-select-card__title">{pipeline.title}</h3>
                <span className="pipeline-select-card__era">{pipeline.era}</span>
              </div>
              <p className="pipeline-select-card__description">{pipeline.description}</p>
              <div className="pipeline-select-card__stages">
                {pipeline.stages.map((stage, i) => (
                  <span key={stage} className="pipeline-select-card__stage">
                    {i > 0 && <span className="pipeline-select-card__arrow">&rarr;</span>}
                    {stage}
                  </span>
                ))}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
