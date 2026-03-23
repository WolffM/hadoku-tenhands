/**
 * OSSDossierPanel — Side drawer overlay
 *
 * Displays a repo dossier from the aggregator in a tabbed side panel.
 * When the aggregator is unavailable, shows a graceful "not available" message.
 */

import { useState, useEffect, useMemo } from 'react'
import { getOSSDossier } from '../../api/endpoints'
import type { Dossier, DossierSections } from '../../api/types'
import { renderMarkdown, DOSSIER_SECTION_ORDER } from '../../utils'
import { LoadingState } from '../common/LoadingState'

const DOSSIER_TAB_LABELS: Record<keyof DossierSections, string> = {
  overview: 'Overview',
  contributionRules: 'Rules',
  successPatterns: 'Success',
  antiPatterns: 'Anti-Patterns',
  issueBoard: 'Issues',
  environmentSetup: 'Setup'
}

interface OSSDossierPanelProps {
  slug: string
  onClose: () => void
}

function DossierContent({
  dossier,
  activeTab,
  setActiveTab
}: {
  dossier: Dossier
  activeTab: keyof DossierSections
  setActiveTab: (t: keyof DossierSections) => void
}) {
  const renderedHtml = useMemo(() => {
    const md = dossier.sections[activeTab]
    if (!md) return ''
    return renderMarkdown(md)
  }, [dossier, activeTab])

  return (
    <>
      <div className="dossier-panel__tabs">
        {DOSSIER_SECTION_ORDER.map(key =>
          dossier.sections[key] ? (
            <button
              key={key}
              className={`dossier-tab ${activeTab === key ? 'dossier-tab--active' : ''}`}
              onClick={() => setActiveTab(key)}
            >
              {DOSSIER_TAB_LABELS[key]}
            </button>
          ) : null
        )}
      </div>
      <div className="dossier-panel__content">
        {renderedHtml ? (
          <div
            className="dossier-panel__markdown markdown-content"
            dangerouslySetInnerHTML={{ __html: renderedHtml }}
          />
        ) : (
          <p className="text-light">No content available for this section.</p>
        )}
      </div>
    </>
  )
}

export function OSSDossierPanel({ slug, onClose }: OSSDossierPanelProps) {
  const [dossier, setDossier] = useState<Dossier | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<keyof DossierSections>('overview')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const result = await getOSSDossier(slug)
        if (result.success && result.dossier) {
          setDossier(result.dossier)
        } else {
          setError('Dossier not available — aggregator may be offline.')
        }
      } catch {
        setError('Failed to load dossier')
      } finally {
        setLoading(false)
      }
    }
    void load()
  }, [slug])

  return (
    <div className="dossier-overlay" onClick={onClose}>
      <div className="dossier-panel" onClick={e => e.stopPropagation()}>
        <div className="dossier-panel__header">
          <h3>Dossier: {slug}</h3>
          <button className="btn btn--secondary btn--sm" onClick={onClose}>
            Close
          </button>
        </div>

        {loading && <LoadingState text="Loading dossier..." />}

        {error && <div className="dossier-panel__error">{error}</div>}

        {dossier && (
          <DossierContent dossier={dossier} activeTab={activeTab} setActiveTab={setActiveTab} />
        )}
      </div>
    </div>
  )
}
