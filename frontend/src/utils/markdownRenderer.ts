import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { DossierSections } from '../api/types'

// Configure marked once at module load — applies to all renderMarkdown calls
marked.setOptions({ breaks: true, gfm: true })

export const DOSSIER_SECTION_ORDER: (keyof DossierSections)[] = [
  'overview',
  'contributionRules',
  'successPatterns',
  'antiPatterns',
  'issueBoard',
  'environmentSetup'
]

/** Parse markdown and sanitize the resulting HTML. */
export function renderMarkdown(md: string): string {
  return DOMPurify.sanitize(marked.parse(md) as string)
}
