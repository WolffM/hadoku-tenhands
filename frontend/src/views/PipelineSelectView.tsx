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
    description: 'Install, run, assign, and review vibecheck across your repos',
    stages: ['Install VibeCheck', 'Run VibeCheck', 'Assign Copilot', 'Review & Merge'],
    icon: '\u{1F50D}'
  },
  {
    id: 'oss' as const,
    title: 'OSS Contribution Pipeline',
    description: 'Repo health, issue selection, pipeline runs, upstream review',
    stages: ['Repo Health', 'Fork & Assign', 'Pipeline Runs', 'Review'],
    icon: '\u{1F310}'
  },
  {
    id: 'temporal' as const,
    title: 'Crimson-Kitty (Temporal)',
    description:
      'Evidence-gated contribution pipeline: per-state artifacts, mechanical gates, operator inbox',
    stages: ['Eligible', 'Reproduced', 'Verified', 'Submittable'],
    icon: '\u{1F408}'
  },
  {
    id: 'taskauto' as const,
    title: 'Task Automation',
    description:
      'Board-driven: a task typed on a phone becomes a plan you approve, then a pull request you merge',
    stages: ['Inbox', 'Plan Review', 'Approved', 'Review & Merge'],
    icon: '\u{1F4CB}'
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
              <h3 className="pipeline-select-card__title">{pipeline.title}</h3>
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
