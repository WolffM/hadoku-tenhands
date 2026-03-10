/**
 * RepoHealthPanel — Tab 1
 *
 * Displays target repos with health scores, dossier sections, and
 * timestamps. Actions: re-scrape and re-compute per repo.
 */

import { useState, useMemo } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { usePipelineStore } from '../../store'
import { refreshOSSTarget, computeOSSTarget } from '../../api/endpoints'
import type { RepoHealthTarget, DossierSections } from '../../api/types'
import { hyphenatedToSlashed } from '../../utils'
import { LoadingState } from '../common/LoadingState'
import { EmptyState } from '../common/EmptyState'
import { Badge, getHealthBadgeVariant } from '../common/Badge'

marked.setOptions({ breaks: true, gfm: true })

const DOSSIER_SECTION_LABELS: Record<keyof DossierSections, string> = {
  overview: 'Overview',
  contributionRules: 'Contribution Rules',
  successPatterns: 'Success Patterns',
  antiPatterns: 'Anti-Patterns',
  issueBoard: 'Issue Board',
  environmentSetup: 'Environment Setup'
}

const SECTION_ORDER: (keyof DossierSections)[] = [
  'overview',
  'contributionRules',
  'successPatterns',
  'antiPatterns',
  'issueBoard',
  'environmentSetup'
]

function DossierSectionsView({ sections }: { sections: DossierSections }) {
  const [expandedSection, setExpandedSection] = useState<string | null>(null)

  // Pre-render all section markdown so toggling is instant
  const rendered = useMemo(() => {
    const out: Partial<Record<keyof DossierSections, string>> = {}
    for (const key of SECTION_ORDER) {
      const md = sections[key]
      if (md) out[key] = DOMPurify.sanitize(marked.parse(md) as string)
    }
    return out
  }, [sections])

  return (
    <div className="repo-health-card__dossier">
      {SECTION_ORDER.map(key => {
        const html = rendered[key]
        if (!html) return null
        const isExpanded = expandedSection === key
        return (
          <div key={key} className="repo-health-card__section">
            <button
              className={`repo-health-card__section-toggle ${isExpanded ? 'repo-health-card__section-toggle--open' : ''}`}
              onClick={() => setExpandedSection(isExpanded ? null : key)}
            >
              <span>{DOSSIER_SECTION_LABELS[key]}</span>
              <span>{isExpanded ? '\u25B2' : '\u25BC'}</span>
            </button>
            {isExpanded && (
              <div
                className="repo-health-card__section-content markdown-content"
                dangerouslySetInnerHTML={{ __html: html }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

export function RepoHealthPanel() {
  const ossStage1 = usePipelineStore(state => state.ossStage1)
  const loadOSSStage1 = usePipelineStore(state => state.loadOSSStage1)
  const addLog = usePipelineStore(state => state.addLog)
  const excludedRepos = usePipelineStore(state => state.ossExcludedRepos)

  const [refreshingSlug, setRefreshingSlug] = useState<string | null>(null)
  const [computingSlug, setComputingSlug] = useState<string | null>(null)

  const handleRefresh = async (slug: string) => {
    setRefreshingSlug(slug)
    addLog(`Re-scraping: ${slug}...`, 'info')
    try {
      const result = await refreshOSSTarget(slug)
      if (result.success) {
        addLog(`Re-scraped: ${slug}`, 'success')
        void loadOSSStage1()
      }
    } catch {
      addLog('Failed to re-scrape', 'error')
    } finally {
      setRefreshingSlug(null)
    }
  }

  const handleCompute = async (slug: string) => {
    setComputingSlug(slug)
    addLog(`Re-computing: ${slug}...`, 'info')
    try {
      const result = await computeOSSTarget(slug)
      if (result.success) {
        addLog(`Re-computed: ${slug}`, 'success')
        void loadOSSStage1()
      }
    } catch {
      addLog('Failed to re-compute', 'error')
    } finally {
      setComputingSlug(null)
    }
  }

  const allTargets = ossStage1.items as RepoHealthTarget[]
  const targets = useMemo(
    () => allTargets.filter(t => !excludedRepos.has(hyphenatedToSlashed(t.slug))),
    [allTargets, excludedRepos]
  )

  if (ossStage1.loading && allTargets.length === 0) {
    return <LoadingState text="Loading repos..." />
  }

  if (targets.length === 0) {
    return (
      <div className="stage-panel">
        <EmptyState
          icon="\u{1F4ED}"
          title="No target repos"
          description="Repos appear here from the aggregator's scored issues."
        />
      </div>
    )
  }

  return (
    <div className="stage-panel">
      <div className="repo-health-grid">
        {targets.map((target: RepoHealthTarget) => {
          const health = target.health
          const dossier = target.dossier
          const analyzedAt = health?.analyzedAt
          const meta = target._meta

          return (
            <div key={target.slug} className="repo-health-card">
              <div className="repo-health-card__header">
                <span className="repo-health-card__slug">{target.slug}</span>
                {health && (
                  <Badge variant={getHealthBadgeVariant(health.overallViability)}>
                    {health.overallViability}
                  </Badge>
                )}
              </div>

              <div className="repo-health-card__scores">
                {health && (
                  <>
                    <div className="repo-health-card__score">
                      <span className="text-light">Maintainer</span>
                      <strong>{health.maintainerHealthScore}%</strong>
                    </div>
                    <div className="repo-health-card__score">
                      <span className="text-light">Merge Access</span>
                      <strong>{health.mergeAccessibilityScore}%</strong>
                    </div>
                    <div className="repo-health-card__score">
                      <span className="text-light">Availability</span>
                      <strong>{health.availabilityScore}%</strong>
                    </div>
                  </>
                )}
              </div>

              <div className="repo-health-card__timestamps">
                {analyzedAt && (
                  <span className="text-light">
                    Analyzed: {new Date(analyzedAt).toLocaleDateString()}
                  </span>
                )}
                {typeof meta?.computedAt === 'string' && (
                  <span className="text-light">
                    Computed: {new Date(meta.computedAt).toLocaleDateString()}
                  </span>
                )}
              </div>

              {dossier?.sections && <DossierSectionsView sections={dossier.sections} />}

              <div className="repo-health-card__actions">
                <button
                  className="btn btn--secondary btn--sm"
                  onClick={() => {
                    void handleRefresh(target.slug)
                  }}
                  disabled={refreshingSlug === target.slug}
                >
                  {refreshingSlug === target.slug ? 'Scraping...' : 'Re-scrape'}
                </button>
                <button
                  className="btn btn--secondary btn--sm"
                  onClick={() => {
                    void handleCompute(target.slug)
                  }}
                  disabled={computingSlug === target.slug}
                >
                  {computingSlug === target.slug ? 'Computing...' : 'Re-compute'}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
