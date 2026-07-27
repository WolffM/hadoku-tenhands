import type { PullRequest } from '../api/types'

type PRReadyInput = Pick<PullRequest, 'isDraft' | 'copilotCompleted' | 'author'>

export function isPRReady(pr: PRReadyInput): boolean {
  const author = pr.author?.login ?? ''
  const isCopilot = author.toLowerCase().includes('copilot')

  if (isCopilot) {
    return pr.copilotCompleted === true
  }
  return !pr.isDraft
}
