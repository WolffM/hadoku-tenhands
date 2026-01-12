/* VibeDispatch Shared Action Functions */

/**
 * Install VibeCheck workflow on a repository
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {HTMLElement} button - Button element to show loading state
 */
async function installVibecheck(owner, repo, button = null) {
  if (button) {
    button.disabled = true
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Installing...'
  }

  log(`Installing VibeCheck on ${repo}...`)

  const result = await apiCall('/api/install-vibecheck', { owner, repo })

  if (result.success) {
    log(`✓ Installed VibeCheck on ${repo}`, 'success')
    if (button) {
      button.innerHTML = '<i class="bi bi-check-lg"></i> Installed'
      button.classList.remove('btn-outline-primary')
      button.classList.add('btn-outline-success')
    }
  } else {
    log(`✗ Failed to install on ${repo}: ${result.error}`, 'error')
    if (button) {
      button.disabled = false
      button.innerHTML = '<i class="bi bi-download"></i> Install'
    }
  }

  return result
}

/**
 * Run VibeCheck workflow on a repository
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {HTMLElement} button - Button element to show loading state
 */
async function runVibecheck(owner, repo, button = null) {
  if (button) {
    button.disabled = true
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Running...'
  }

  log(`Running VibeCheck on ${repo}...`)

  const result = await apiCall('/api/run-vibecheck', { owner, repo })

  if (result.success) {
    log(`✓ Triggered VibeCheck on ${repo}`, 'success')
    if (button) {
      button.innerHTML = '<i class="bi bi-check-lg"></i> Triggered'
      button.classList.remove('btn-outline-primary')
      button.classList.add('btn-outline-success')
    }
  } else {
    log(`✗ Failed to run on ${repo}: ${result.error}`, 'error')
    if (button) {
      button.disabled = false
      button.innerHTML = '<i class="bi bi-play-fill"></i> Run'
    }
  }

  return result
}

/**
 * Assign Copilot to an issue
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {number} issueNumber - Issue number
 * @param {HTMLElement} button - Button element to show loading state
 */
async function assignCopilot(owner, repo, issueNumber, button = null) {
  if (button) {
    button.disabled = true
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Assigning...'
  }

  log(`Assigning Copilot to ${repo}#${issueNumber}...`)

  const result = await apiCall('/api/assign-copilot', { owner, repo, issue_number: issueNumber })

  if (result.success) {
    log(`✓ Assigned Copilot to ${repo}#${issueNumber}`, 'success')
    if (button) {
      button.innerHTML = '<i class="bi bi-check-lg"></i> Assigned'
      button.classList.remove('btn-outline-warning')
      button.classList.add('btn-outline-success')
    }
  } else {
    log(`✗ Failed to assign on ${repo}#${issueNumber}: ${result.error}`, 'error')
    if (button) {
      button.disabled = false
      button.innerHTML = '<i class="bi bi-robot"></i> Assign'
    }
  }

  return result
}

/**
 * Approve a pull request
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {number} prNumber - PR number
 * @param {HTMLElement} button - Button element to show loading state
 */
async function approvePR(owner, repo, prNumber, button = null) {
  if (button) {
    button.disabled = true
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>'
  }

  log(`Approving ${repo}#${prNumber}...`)

  const result = await apiCall('/api/approve-pr', { owner, repo, pr_number: prNumber })

  if (result.success) {
    log(`✓ Approved ${repo}#${prNumber}`, 'success')
    if (button) {
      button.innerHTML = '<i class="bi bi-check-lg"></i>'
      button.classList.remove('btn-outline-success')
      button.classList.add('btn-success')
    }
  } else {
    log(`✗ Failed to approve ${repo}#${prNumber}: ${result.error}`, 'error')
    if (button) {
      button.disabled = false
      button.innerHTML = '<i class="bi bi-check-lg"></i>'
    }
  }

  return result
}

/**
 * Merge a pull request
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {number} prNumber - PR number
 * @param {HTMLElement} button - Button element to show loading state
 */
async function mergePR(owner, repo, prNumber, button = null) {
  if (button) {
    button.disabled = true
    button.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>'
  }

  log(`Merging ${repo}#${prNumber}...`)

  const result = await apiCall('/api/merge-pr', { owner, repo, pr_number: prNumber })

  if (result.success) {
    log(`✓ Merged ${repo}#${prNumber}`, 'success')
    if (button) {
      button.innerHTML = '<i class="bi bi-check-lg"></i>'
      button.classList.remove('btn-outline-primary')
      button.classList.add('btn-success')
    }
  } else {
    log(`✗ Failed to merge ${repo}#${prNumber}: ${result.error}`, 'error')
    if (button) {
      button.disabled = false
      button.innerHTML = '<i class="bi bi-git"></i>'
    }
  }

  return result
}

/**
 * Mark a draft PR as ready for review
 * @param {string} owner - Repository owner
 * @param {string} repo - Repository name
 * @param {number} prNumber - PR number
 * @param {HTMLElement} button - Button element to show loading state
 */
async function markPRReady(owner, repo, prNumber, button = null) {
  if (button) {
    button.disabled = true
    button.innerHTML = '<span class="spinner-border spinner-border-sm"></span>'
  }

  log(`Marking ${repo}#${prNumber} as ready for review...`)

  const result = await apiCall('/api/mark-pr-ready', { owner, repo, pr_number: prNumber })

  if (result.success) {
    log(`✓ ${repo}#${prNumber} is now ready for review`, 'success')
    if (button) {
      button.innerHTML = '<i class="bi bi-check-lg"></i>'
      button.classList.remove('btn-outline-warning')
      button.classList.add('btn-success')
    }
  } else {
    log(`✗ Failed to mark ${repo}#${prNumber} as ready: ${result.error}`, 'error')
    if (button) {
      button.disabled = false
      button.innerHTML = '<i class="bi bi-check2-square"></i>'
    }
  }

  return result
}
