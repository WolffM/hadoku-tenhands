/**
 * Global Actions Page - Stage Management Functions
 * This file contains all the JavaScript logic for the Global Actions pipeline page.
 */

/**
 * Make authenticated fetch request with admin key
 * @param {string} url - URL to fetch
 * @param {object} options - Fetch options (optional)
 * @returns {Promise<Response>} Fetch response
 */
async function authFetch(url, options = {}) {
  const adminKey = getAdminKey()
  const headers = options.headers || {}
  if (adminKey) {
    headers['X-User-Key'] = adminKey
  }
  return fetch(url, { ...options, headers })
}

// ============ State Variables ============
let stage1Data = []
let stage2Data = []
let stage3Data = []
let stage3AllIssues = []
let stage3ReposWithCopilotPRs = []
let stage4Data = []
let currentPR = null
let currentPRIndex = 0

// Owner is set from template
let owner = ''

/**
 * Initialize the global actions page
 * @param {string} ownerName - The GitHub owner/org name
 */
function initGlobalActions(ownerName) {
  owner = ownerName

  // Load all stages in parallel on page load
  loadStage1()
  loadStage2()
  loadStage3()
  loadStage4()
}

// ============ Stage 1: Install VibeCheck ============
async function loadStage1() {
  const container = document.getElementById('stage1-content')
  container.innerHTML = loadingSpinner()

  try {
    const response = await authFetch((window.URL_PREFIX || '') + '/api/stage1-repos')
    const data = await response.json()

    if (data.success) {
      stage1Data = data.repos
      document.getElementById('stage1-count').textContent = data.repos.length
      renderStage1(data.repos)
    }
  } catch (error) {
    container.innerHTML = '<p class="text-danger">Error loading data</p>'
  }
}

function renderStage1(repos) {
  const container = document.getElementById('stage1-content')

  if (repos.length === 0) {
    container.innerHTML =
      '<p class="text-success text-center py-4"><i class="bi bi-check-circle-fill"></i> All repos have VibeCheck installed!</p>'
    return
  }

  let html = `
        <div class="mb-3">
            <button class="btn btn-sm btn-outline-primary me-2" onclick="selectAll('.stage1-checkbox')">Select All</button>
            <button class="btn btn-sm btn-outline-secondary" onclick="selectNone('.stage1-checkbox')">Select None</button>
        </div>
        <div class="row">
    `

  for (const repo of repos) {
    html += `
            <div class="col-md-4 col-lg-3 mb-2">
                <div class="form-check">
                    <input class="form-check-input stage1-checkbox" type="checkbox" value="${repo.name}" id="s1-${repo.name}">
                    <label class="form-check-label" for="s1-${repo.name}">
                        ${repo.name}
                        ${repo.isPrivate ? '<i class="bi bi-lock-fill text-secondary ms-1"></i>' : ''}
                    </label>
                </div>
            </div>
        `
  }

  html += '</div>'
  container.innerHTML = html
}

async function installSelectedStage1() {
  const selected = getSelectedValues('.stage1-checkbox')
  if (selected.length === 0) {
    showToast('Warning', 'Select at least one repo', 'info')
    return
  }

  log(`Installing VibeCheck on ${selected.length} repos...`)

  const successful = await batchOperation(
    selected,
    async repo => {
      log(`Installing on ${repo}...`)
      return await apiCall('/api/install-vibecheck', { owner, repo })
    },
    {
      onSuccess: repo => log(`✓ Installed on ${repo}`, 'success'),
      onError: (repo, result) => log(`✗ Failed on ${repo}: ${result?.error}`, 'error')
    }
  )

  log(`Done! Installed on ${successful.length}/${selected.length} repos`, 'success')
  setTimeout(loadStage1, 1000)
}

// ============ Stage 2: Run VibeCheck ============
async function loadStage2() {
  const container = document.getElementById('stage2-content')
  container.innerHTML = loadingSpinner('Loading repos with commit info...')

  try {
    const response = await authFetch((window.URL_PREFIX || '') + '/api/stage2-repos')
    const data = await response.json()

    if (data.success) {
      stage2Data = data.repos
      document.getElementById('stage2-count').textContent = data.repos.length
      renderStage2(data.repos)
    }
  } catch (error) {
    container.innerHTML = '<p class="text-danger">Error loading data</p>'
  }
}

function renderStage2(repos) {
  const container = document.getElementById('stage2-content')

  if (repos.length === 0) {
    container.innerHTML =
      '<p class="text-secondary text-center py-4">No repos with VibeCheck installed</p>'
    return
  }

  // Split repos into recommended (needs run) and others
  const recommended = repos.filter(repo => {
    const lastRun = repo.lastRun
    const status = lastRun ? lastRun.conclusion || lastRun.status : 'none'
    const isRunning = status === 'in_progress' || status === 'queued' || status === 'triggered'
    const needsRun = !lastRun || repo.commitsSinceLastRun > 0
    return needsRun && !isRunning
  })
  const others = repos.filter(repo => !recommended.includes(repo))

  let html = ''

  // Recommended section
  if (recommended.length > 0) {
    html += `
            <div class="mb-4">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="text-warning mb-0"><i class="bi bi-star-fill"></i> Recommended (${recommended.length} repos need VibeCheck)</h6>
                    <button class="btn btn-sm btn-outline-warning" onclick="runAllRecommendedStage2()">
                        <i class="bi bi-play-fill"></i> Run All Recommended
                    </button>
                </div>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th style="width: 30px;"></th>
                                <th>Repository</th>
                                <th>Last Run</th>
                                <th>Commits Since</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody>
        `

    for (const repo of recommended) {
      const lastRun = repo.lastRun
      const lastRunTime = lastRun ? formatTimeAgo(lastRun.createdAt) : 'Never'
      const commits = repo.commitsSinceLastRun

      html += `
                <tr>
                    <td>
                        <input class="form-check-input stage2-recommended-checkbox" type="checkbox" value="${repo.name}" checked>
                    </td>
                    <td>
                        <a href="/repo/${owner}/${repo.name}" class="text-decoration-none">${repo.name}</a>
                    </td>
                    <td class="text-secondary">${lastRunTime}</td>
                    <td>
                        ${commits > 0 ? `<span class="badge bg-warning">${commits} new</span>` : '<span class="text-secondary">Never run</span>'}
                    </td>
                    <td>
                        <button class="btn btn-sm btn-outline-primary" onclick="runSingleVibecheck('${repo.name}')" title="Run VibeCheck">
                            <i class="bi bi-play-fill"></i>
                        </button>
                    </td>
                </tr>
            `
    }

    html += '</tbody></table></div></div>'
    html += '<hr class="border-secondary">'
  }

  // All repos section (or just the others if we have recommended)
  html += `
        <div class="mb-3">
            <h6 class="text-secondary mb-2">${recommended.length > 0 ? 'Other Repos' : 'All Repos'}</h6>
            <button class="btn btn-sm btn-outline-primary me-2" onclick="selectAll('.stage2-checkbox')">Select All</button>
            <button class="btn btn-sm btn-outline-secondary" onclick="selectNone('.stage2-checkbox')">Select None</button>
        </div>
        <div class="table-responsive">
            <table class="table table-sm">
                <thead>
                    <tr>
                        <th style="width: 30px;"></th>
                        <th>Repository</th>
                        <th>Last Run</th>
                        <th>Status</th>
                        <th>Commits Since</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
    `

  const reposToShow = recommended.length > 0 ? others : repos

  for (const repo of reposToShow) {
    const lastRun = repo.lastRun
    const lastRunTime = lastRun ? formatTimeAgo(lastRun.createdAt) : 'Never'
    const status = lastRun ? lastRun.conclusion || lastRun.status : 'none'
    const commits = repo.commitsSinceLastRun
    const needsRun = !lastRun || commits > 0
    const isRunning = status === 'in_progress' || status === 'queued' || status === 'triggered'
    const canRun = needsRun && !isRunning

    html += `
            <tr>
                <td>
                    <input class="form-check-input stage2-checkbox" type="checkbox" value="${repo.name}" 
                           data-needs-run="${needsRun}" ${!canRun ? 'disabled' : ''}>
                </td>
                <td>
                    <a href="/repo/${owner}/${repo.name}" class="text-decoration-none">${repo.name}</a>
                </td>
                <td class="text-secondary">${lastRunTime}</td>
                <td>${getStatusBadge(status)}</td>
                <td>
                    ${commits > 0 ? `<span class="badge bg-warning">${commits} new</span>` : '<span class="text-secondary">0</span>'}
                </td>
                <td>
                    <button class="btn btn-sm btn-outline-primary" onclick="runSingleVibecheck('${repo.name}')" 
                            ${!canRun ? 'disabled' : ''} title="${!canRun ? (isRunning ? 'Already running' : 'No new commits') : 'Run VibeCheck'}">
                        <i class="bi bi-play-fill"></i>
                    </button>
                </td>
            </tr>
        `
  }

  html += '</tbody></table></div>'
  container.innerHTML = html
}

async function runAllRecommendedStage2() {
  const selected = getSelectedValues('.stage2-recommended-checkbox')
  if (selected.length === 0) {
    showToast('Warning', 'No recommended repos selected', 'info')
    return
  }

  setBatchUIState(
    '[onclick="runAllRecommendedStage2()"]',
    '.stage2-checkbox, .stage2-recommended-checkbox',
    true,
    'Running...'
  )

  log(`Running VibeCheck on ${selected.length} recommended repos...`)

  const successful = await batchOperation(
    selected,
    async repo => {
      log(`Triggering on ${repo}...`)
      const result = await apiCall('/api/run-vibecheck', { owner, repo })
      if (result.success) updateRepoStatus(repo, 'triggered')
      return result
    },
    {
      onSuccess: repo => log(`✓ Triggered on ${repo}`, 'success'),
      onError: (repo, result) => log(`✗ Failed on ${repo}: ${result?.error}`, 'error')
    }
  )

  setBatchUIState(
    '[onclick="runAllRecommendedStage2()"]',
    '.stage2-checkbox, .stage2-recommended-checkbox',
    false
  )
  log(`All workflows triggered! (${successful.length}/${selected.length} successful)`, 'success')
  if (successful.length > 0) {
    showToast('Success', `Triggered VibeCheck on ${successful.length} repos`, 'success')
  }

  // Reload after a delay to show updated status
  setTimeout(loadStage2, 2000)
}

function selectNeedsRunStage2() {
  document.querySelectorAll('.stage2-checkbox').forEach(cb => {
    cb.checked = cb.dataset.needsRun === 'true'
  })
}

async function runSelectedStage2() {
  const selected = getSelectedValues('.stage2-checkbox')
  if (selected.length === 0) {
    showToast('Warning', 'Select at least one repo', 'info')
    return
  }

  log(`Running VibeCheck on ${selected.length} repos...`)

  const successful = await batchOperation(
    selected,
    async repo => {
      log(`Triggering on ${repo}...`)
      const result = await apiCall('/api/run-vibecheck', { owner, repo })
      if (result.success) updateRepoStatus(repo, 'triggered')
      return result
    },
    {
      onSuccess: repo => log(`✓ Triggered on ${repo}`, 'success'),
      onError: (repo, result) => log(`✗ Failed on ${repo}: ${result?.error}`, 'error')
    }
  )

  log(`All workflows triggered! (${successful.length}/${selected.length} successful)`, 'success')
  if (successful.length > 0) {
    showToast('Success', `Triggered VibeCheck on ${successful.length} repos`, 'success')
  }
}

async function runSingleVibecheck(repo) {
  log(`Running VibeCheck on ${repo}...`)
  updateRepoStatus(repo, 'triggered')

  const result = await apiCall('/api/run-vibecheck', { owner, repo })
  if (result.success) {
    log(`✓ Triggered on ${repo}`, 'success')
    showToast('Success', `VibeCheck triggered on ${repo}`, 'success')
  } else {
    log(`✗ Failed on ${repo}: ${result.error}`, 'error')
    updateRepoStatus(repo, 'error')
  }
}

function updateRepoStatus(repoName, newStatus) {
  const rows = document.querySelectorAll('#stage2-content table tbody tr')
  for (const row of rows) {
    const repoLink = row.querySelector('td:nth-child(2) a')
    if (repoLink && repoLink.textContent === repoName) {
      const statusCell = row.querySelector('td:nth-child(4)')
      if (statusCell) {
        statusCell.innerHTML = getStatusBadge(newStatus)
      }
      const checkbox = row.querySelector('.stage2-checkbox')
      if (checkbox) checkbox.checked = false
      break
    }
  }
}

// ============ Stage 3: Assign Copilot ============
async function loadStage3() {
  const container = document.getElementById('stage3-content')
  container.innerHTML = loadingSpinner()

  try {
    const response = await authFetch((window.URL_PREFIX || '') + '/api/stage3-issues')
    const data = await response.json()

    if (data.success) {
      stage3AllIssues = data.issues
      stage3Data = data.issues
      stage3ReposWithCopilotPRs = data.repos_with_copilot_prs || []
      document.getElementById('stage3-count').textContent = data.issues.length

      // Populate label filter
      const labelFilter = document.getElementById('stage3-label-filter')
      labelFilter.innerHTML = '<option value="all">All Labels</option>'
      for (const label of data.labels) {
        if (label && !label.startsWith('severity:') && !label.startsWith('confidence:')) {
          labelFilter.innerHTML += `<option value="${label}">${label}</option>`
        }
      }

      renderStage3(data.issues)
    }
  } catch (error) {
    container.innerHTML = '<p class="text-danger">Error loading data</p>'
  }
}

function filterStage3() {
  const severityFilter = document.getElementById('stage3-severity-filter').value
  const labelFilter = document.getElementById('stage3-label-filter').value

  let filtered = stage3AllIssues

  if (severityFilter !== 'all') {
    filtered = filtered.filter(issue =>
      issue.labels.some(l => l.name.toLowerCase().includes(severityFilter.toLowerCase()))
    )
  }

  if (labelFilter !== 'all') {
    filtered = filtered.filter(issue => issue.labels.some(l => l.name === labelFilter))
  }

  stage3Data = filtered
  renderStage3(filtered)
}

function getRecommendedIssues(issues) {
  const repoIssues = {}
  for (const issue of issues) {
    const repo = issue.repo
    if (stage3ReposWithCopilotPRs.includes(repo)) continue
    if (!repoIssues[repo]) {
      repoIssues[repo] = issue
    }
  }
  return Object.values(repoIssues)
}

function renderStage3(issues) {
  const container = document.getElementById('stage3-content')

  if (issues.length === 0) {
    container.innerHTML =
      '<p class="text-secondary text-center py-4">No issues found matching filters</p>'
    return
  }

  const recommended = getRecommendedIssues(issues)

  let html = ''

  // Recommended issues section
  if (recommended.length > 0) {
    html += `
            <div class="mb-4">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="text-warning mb-0"><i class="bi bi-star-fill"></i> Recommended (1 per repo, no active Copilot PRs)</h6>
                    <div>
                        <button class="btn btn-sm btn-outline-secondary" onclick="selectAll('.stage3-recommended-checkbox')">Select All</button>
                    </div>
                </div>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th style="width: 30px;"></th>
                                <th>Repo</th>
                                <th>#</th>
                                <th>Title</th>
                                <th>Severity</th>
                            </tr>
                        </thead>
                        <tbody>
        `

    for (const issue of recommended) {
      const severity = getSeverity(issue)
      const severityClass = getSeverityClass(severity)

      html += `
                <tr>
                    <td>
                        <input class="form-check-input stage3-recommended-checkbox" type="checkbox" 
                               value="${issue.repo}:${issue.number}">
                    </td>
                    <td><a href="/repo/${owner}/${issue.repo}" class="text-decoration-none">${issue.repo}</a></td>
                    <td class="text-light">${issue.number}</td>
                    <td>
                        <a href="${issue.url}" target="_blank" class="text-decoration-none">
                            ${issue.title.substring(0, 45)}${issue.title.length > 45 ? '...' : ''}
                        </a>
                    </td>
                    <td><span class="${severityClass}">${severity}</span></td>
                </tr>
            `
    }

    html += '</tbody></table></div></div>'
    html += '<hr class="border-secondary">'
  }

  // All issues section
  html += `
        <div class="mb-3">
            <h6 class="text-secondary mb-2">All Issues</h6>
            <button class="btn btn-sm btn-outline-primary me-2" onclick="selectAll('.stage3-checkbox')">Select All</button>
            <button class="btn btn-sm btn-outline-secondary" onclick="selectNone('.stage3-checkbox')">Select None</button>
        </div>
        <div class="table-responsive">
            <table class="table table-sm">
                <thead>
                    <tr>
                        <th style="width: 30px;"></th>
                        <th>Repo</th>
                        <th>#</th>
                        <th>Title</th>
                        <th>Severity</th>
                        <th>Labels</th>
                    </tr>
                </thead>
                <tbody>
    `

  for (const issue of issues) {
    const severity = getSeverity(issue)
    const severityClass = getSeverityClass(severity)

    const otherLabels = issue.labels
      .filter(
        l =>
          !l.name.startsWith('severity:') &&
          l.name !== 'vibeCheck' &&
          !l.name.startsWith('confidence:')
      )
      .slice(0, 2)
      .map(l => `<span class="badge bg-secondary me-1">${l.name}</span>`)
      .join('')

    html += `
            <tr>
                <td>
                    <input class="form-check-input stage3-checkbox" type="checkbox" 
                           value="${issue.repo}:${issue.number}">
                </td>
                <td><a href="/repo/${owner}/${issue.repo}" class="text-decoration-none">${issue.repo}</a></td>
                <td class="text-light">${issue.number}</td>
                <td>
                    <a href="${issue.url}" target="_blank" class="text-decoration-none">
                        ${issue.title.substring(0, 50)}${issue.title.length > 50 ? '...' : ''}
                    </a>
                </td>
                <td><span class="${severityClass}">${severity}</span></td>
                <td>${otherLabels}</td>
            </tr>
        `
  }

  html += '</tbody></table></div>'
  container.innerHTML = html
}

async function assignRecommended() {
  const selected = getSelectedValues('.stage3-recommended-checkbox')
  if (selected.length === 0) {
    showToast('Warning', 'No recommended issues selected', 'info')
    return
  }

  setBatchUIState(
    '[onclick="assignRecommended()"]',
    '.stage3-checkbox, .stage3-recommended-checkbox',
    true,
    'Assigning...'
  )

  log(`Assigning Copilot to ${selected.length} recommended issues...`)

  const successful = await batchOperation(
    selected,
    async item => {
      const [repo, issueNumber] = item.split(':')
      log(`Assigning Copilot to ${repo}#${issueNumber}...`)
      return await apiCall('/api/assign-copilot', {
        owner,
        repo,
        issue_number: parseInt(issueNumber)
      })
    },
    {
      onSuccess: item => {
        const [repo, num] = item.split(':')
        log(`✓ Assigned to ${repo}#${num}`, 'success')
      },
      onError: (item, result) => {
        const [repo, num] = item.split(':')
        log(`✗ Failed on ${repo}#${num}: ${result?.error}`, 'error')
      }
    }
  )

  removeAssignedIssues(successful)
  setBatchUIState(
    '[onclick="assignRecommended()"]',
    '.stage3-checkbox, .stage3-recommended-checkbox',
    false
  )
  log(`Done! Assigned Copilot to ${successful.length}/${selected.length} issues`, 'success')
  showToast('Success', `Assigned Copilot to ${successful.length} issues`, 'success')
}

async function assignSelectedStage3() {
  const selectedRecommended = getSelectedValues('.stage3-recommended-checkbox')
  const selectedAll = getSelectedValues('.stage3-checkbox')
  const selected = [...new Set([...selectedRecommended, ...selectedAll])]

  if (selected.length === 0) {
    showToast('Warning', 'Select at least one issue', 'info')
    return
  }

  setBatchUIState(
    '[onclick="assignSelectedStage3()"]',
    '.stage3-checkbox, .stage3-recommended-checkbox',
    true,
    'Assigning...'
  )

  log(`Assigning Copilot to ${selected.length} issues...`)

  const successful = await batchOperation(
    selected,
    async item => {
      const [repo, issueNumber] = item.split(':')
      log(`Assigning Copilot to ${repo}#${issueNumber}...`)
      return await apiCall('/api/assign-copilot', {
        owner,
        repo,
        issue_number: parseInt(issueNumber)
      })
    },
    {
      onSuccess: item => {
        const [repo, num] = item.split(':')
        log(`✓ Assigned to ${repo}#${num}`, 'success')
      },
      onError: (item, result) => {
        const [repo, num] = item.split(':')
        log(`✗ Failed on ${repo}#${num}: ${result?.error}`, 'error')
      }
    }
  )

  removeAssignedIssues(successful)
  setBatchUIState(
    '[onclick="assignSelectedStage3()"]',
    '.stage3-checkbox, .stage3-recommended-checkbox',
    false
  )
  log(`Done! Assigned Copilot to ${successful.length}/${selected.length} issues`, 'success')
  showToast('Success', `Assigned Copilot to ${successful.length} issues`, 'success')
}

function removeAssignedIssues(items) {
  for (const item of items) {
    const [repo, issueNumber] = item.split(':')
    const num = parseInt(issueNumber)
    stage3AllIssues = stage3AllIssues.filter(i => !(i.repo === repo && i.number === num))
    stage3Data = stage3Data.filter(i => !(i.repo === repo && i.number === num))
    // Add repo to list of repos with Copilot PRs so it's excluded from recommended
    if (!stage3ReposWithCopilotPRs.includes(repo)) {
      stage3ReposWithCopilotPRs.push(repo)
    }
  }
  document.getElementById('stage3-count').textContent = stage3AllIssues.length
  renderStage3(stage3Data)
}

// ============ Stage 4: Review & Merge ============
async function loadStage4() {
  const container = document.getElementById('stage4-content')
  container.innerHTML = loadingSpinner()

  try {
    const response = await authFetch((window.URL_PREFIX || '') + '/api/stage4-prs')
    const data = await response.json()

    if (data.success) {
      stage4Data = data.prs
      // Ready PRs: non-draft OR Copilot PRs that are completed
      const readyPrs = data.prs.filter(pr => isPRReady(pr))
      document.getElementById('stage4-count').textContent = readyPrs.length
      renderStage4(data.prs)
    }
  } catch (error) {
    container.innerHTML = '<p class="text-danger">Error loading data</p>'
  }
}

/**
 * Check if a PR is ready for review
 * For Copilot PRs: ready when copilotCompleted is true (title not [WIP] or completion comment)
 * For other PRs: ready when not draft
 */
function isPRReady(pr) {
  const author = pr.author ? pr.author.login : ''
  const isCopilot = author.toLowerCase().includes('copilot')

  if (isCopilot) {
    // Copilot PR: check if completed (title no longer [WIP] or has completion comment)
    return pr.copilotCompleted === true
  }
  // Non-Copilot PR: use draft status
  return !pr.isDraft
}

function renderStage4(prs) {
  const container = document.getElementById('stage4-content')

  if (prs.length === 0) {
    container.innerHTML = '<p class="text-secondary text-center py-4">No open pull requests</p>'
    return
  }

  const inProgress = prs.filter(pr => !isPRReady(pr))
  const readyForReview = prs.filter(pr => isPRReady(pr))

  let html = ''

  // Ready for Review section
  if (readyForReview.length > 0) {
    html += `
            <div class="mb-4">
                <h6 class="text-success mb-2"><i class="bi bi-check-circle-fill"></i> Ready for Review (${readyForReview.length})</h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Repo</th>
                                <th>Title</th>
                                <th>Branch</th>
                                <th>Author</th>
                                <th>Status</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
        `

    for (const pr of readyForReview) {
      html += renderPRRow(pr, true)
    }

    html += '</tbody></table></div></div>'
  } else {
    html +=
      '<p class="text-secondary mb-4"><i class="bi bi-info-circle"></i> No PRs ready for review</p>'
  }

  // In Progress section
  if (inProgress.length > 0) {
    html += `
            <hr class="border-secondary">
            <div>
                <h6 class="text-warning mb-2"><i class="bi bi-hourglass-split"></i> In Progress / Draft (${inProgress.length})</h6>
                <div class="table-responsive">
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Repo</th>
                                <th>Title</th>
                                <th>Branch</th>
                                <th>Author</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
        `

    for (const pr of inProgress) {
      html += renderPRRow(pr, false)
    }

    html += '</tbody></table></div></div>'
  }

  container.innerHTML = html
}

function renderPRRow(pr, showReviewStatus) {
  const author = pr.author ? pr.author.login : 'unknown'
  const isCopilot = author.toLowerCase().includes('copilot')
  const isReady = isPRReady(pr)

  // Build status badges with dark mode compatible colors
  let statusBadges = ''
  if (pr.isDraft) {
    statusBadges += '<span class="badge badge-draft ms-1">Draft</span>'
  }
  if (isCopilot && pr.copilotCompleted === false) {
    statusBadges += '<span class="badge badge-wip ms-1">WIP</span>'
  }

  // Review status for ready PRs
  let reviewBadge = ''
  if (showReviewStatus) {
    if (pr.reviewDecision === 'APPROVED') {
      reviewBadge = '<span class="badge bg-success">Approved</span>'
    } else if (pr.reviewDecision === 'CHANGES_REQUESTED') {
      reviewBadge = '<span class="badge bg-danger">Changes</span>'
    } else {
      reviewBadge = '<span class="badge badge-pending">Pending</span>'
    }
  }

  // Cleaner title display - strip [WIP] prefix since we show it as badge
  let displayTitle = pr.title.replace(/^\[WIP\]\s*/i, '')
  if (displayTitle.length > 40) {
    displayTitle = displayTitle.substring(0, 40) + '...'
  }

  return `
        <tr>
            <td>
                <a href="/repo/${owner}/${pr.repo}" class="text-decoration-none">${pr.repo}</a>
                <span class="text-secondary">#${pr.number}</span>
            </td>
            <td>
                <a href="${pr.url}" target="_blank" class="text-decoration-none" title="${escapeHtml(pr.title)}">
                    ${escapeHtml(displayTitle)}
                </a>
                ${statusBadges}
            </td>
            <td><code class="branch-name" title="${escapeHtml(pr.headRefName)}">${pr.headRefName}</code></td>
            <td>
                ${isCopilot ? '<i class="bi bi-robot text-warning"></i>' : '<i class="bi bi-person text-secondary"></i>'} 
                <span class="text-secondary">${escapeHtml(author.replace('app/', ''))}</span>
            </td>
            ${showReviewStatus ? `<td>${reviewBadge}</td>` : ''}
            <td class="text-secondary">${formatTimeAgo(pr.createdAt)}</td>
            <td>
                <div class="pr-actions">
                    <button class="btn btn-icon btn-outline-secondary" onclick="showPRDetails('${pr.repo}', ${pr.number})" title="View Details">
                        <i class="bi bi-eye"></i>
                    </button>
                    ${
                      isReady
                        ? `
                        <button class="btn btn-icon btn-outline-success" onclick="quickApprovePR('${pr.repo}', ${pr.number})" title="Approve">
                            <i class="bi bi-check-lg"></i>
                        </button>
                        <button class="btn btn-icon btn-outline-primary" onclick="quickMergePR('${pr.repo}', ${pr.number})" title="Merge">
                            <i class="bi bi-git"></i>
                        </button>
                    `
                        : `
                        <button class="btn btn-icon btn-outline-secondary" disabled title="Copilot still working...">
                            <i class="bi bi-hourglass-split"></i>
                        </button>
                    `
                    }
                </div>
            </td>
        </tr>
    `
}

async function markPRReadyStage4(repo, prNumber) {
  log(`Marking ${repo}#${prNumber} as ready for review...`)
  const result = await markPRReady(owner, repo, prNumber)
  if (result.success) {
    loadStage4()
  }
}

// Quick actions that use shared functions from actions.js
async function quickApprovePR(repo, prNumber) {
  await approvePR(owner, repo, prNumber)
}

async function quickMergePR(repo, prNumber) {
  removePRFromList(repo, prNumber)

  const result = await mergePR(owner, repo, prNumber)
  if (!result.success) {
    loadStage4() // Reload on failure to restore state
  }
}

async function showPRDetails(repo, prNumber) {
  currentPR = { repo, number: prNumber }

  // Find current index in the ready PRs list
  const readyPrs = stage4Data.filter(pr => isPRReady(pr))
  currentPRIndex = readyPrs.findIndex(pr => pr.repo === repo && pr.number === prNumber)
  if (currentPRIndex === -1) currentPRIndex = 0

  // Update navigation counter and button states
  updatePRNav()

  const modalEl = document.getElementById('prModal')
  let modal = bootstrap.Modal.getInstance(modalEl)
  if (!modal) {
    modal = new bootstrap.Modal(modalEl)
  }

  document.getElementById('prModalTitle').textContent = `${repo} #${prNumber}`
  document.getElementById('prModalSubtitle').textContent = 'Loading...'
  document.getElementById('prModalInfo').innerHTML = loadingSpinner()
  document.getElementById('prModalDiff').innerHTML =
    '<div class="text-center py-4 text-secondary">Loading diff...</div>'
  document.getElementById('prStats').textContent = ''

  modal.show()

  const result = await apiCall('/api/pr-details', { owner, repo, pr_number: prNumber })

  if (result.success) {
    const pr = result.pr
    document.getElementById('prModalTitle').textContent = pr.title
    document.getElementById('prModalSubtitle').textContent = `${repo} #${prNumber}`

    // Build info sidebar
    let filesHtml = ''
    if (pr.files && pr.files.length > 0) {
      filesHtml =
        '<div class="mt-3"><h6 class="text-light mb-2">Changed Files</h6><div class="list-group list-group-flush">'
      for (const file of pr.files) {
        const fileName = file.path.split('/').pop()
        filesHtml += `
                    <a href="#diff-${file.path.replace(/[^a-zA-Z0-9]/g, '-')}" class="list-group-item list-group-item-action bg-transparent text-light border-secondary py-1 px-2">
                        <small class="d-flex justify-content-between">
                            <span class="text-truncate me-2" title="${file.path}">${fileName}</span>
                            <span class="text-nowrap">
                                <span class="text-success">+${file.additions}</span>
                                <span class="text-danger">-${file.deletions}</span>
                            </span>
                        </small>
                    </a>
                `
      }
      filesHtml += '</div></div>'
    }

    let bodyHtml = pr.body || 'No description'
    if (bodyHtml.length > 500) {
      bodyHtml = bodyHtml.substring(0, 500) + '...'
    }
    bodyHtml = escapeHtml(bodyHtml)
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/`(.*?)`/g, '<code>$1</code>')
      .replace(/\n/g, '<br>')

    const draftBadge = pr.isDraft ? '<span class="badge bg-warning ms-2">Draft</span>' : ''

    document.getElementById('prModalInfo').innerHTML = `
            <div class="mb-3">
                <span class="badge bg-primary">${escapeHtml(pr.headRefName)}</span>
                ${draftBadge}
                <div class="text-secondary small mt-1">
                    <i class="bi bi-arrow-right"></i> ${escapeHtml(pr.baseRefName)}
                </div>
            </div>
            
            <div class="mb-3 text-secondary small">
                <div><i class="bi bi-person"></i> ${pr.author ? escapeHtml(pr.author.login) : 'unknown'}</div>
                <div><i class="bi bi-clock"></i> ${formatTimeAgo(pr.createdAt)}</div>
                <div><i class="bi bi-file-diff"></i> ${pr.commits ? pr.commits.length : 0} commits</div>
            </div>
            
            <div class="mb-3">
                <h6 class="text-light mb-2">Description</h6>
                <div class="text-secondary small" style="max-height: 200px; overflow-y: auto;">
                    ${bodyHtml}
                </div>
            </div>
            
            ${filesHtml}
            
            <div class="mt-3">
                <a href="${pr.url}" target="_blank" class="btn btn-sm btn-outline-primary w-100">
                    <i class="bi bi-github"></i> View on GitHub
                </a>
            </div>
        `

    document.getElementById('prStats').innerHTML = `
            <span class="text-success">+${pr.additions || 0}</span> 
            <span class="text-danger">-${pr.deletions || 0}</span>
            in ${pr.changedFiles || (pr.files ? pr.files.length : 0)} files
        `

    if (pr.diff) {
      document.getElementById('prModalDiff').innerHTML = renderDiff(pr.diff)
    } else {
      document.getElementById('prModalDiff').innerHTML =
        '<p class="text-secondary p-3">No diff available</p>'
    }
  } else {
    document.getElementById('prModalInfo').innerHTML =
      '<p class="text-danger">Failed to load PR details</p>'
  }
}

// Modal actions - use shared functions from actions.js
async function approveCurrentPR() {
  if (!currentPR) return
  await approvePR(owner, currentPR.repo, currentPR.number)
}

async function mergeCurrentPR() {
  if (!currentPR) return

  const prToMerge = { ...currentPR }
  removePRFromList(prToMerge.repo, prToMerge.number)

  // Show next PR immediately (don't wait for merge)
  showNextPR()

  // Fire off merge in background
  mergePR(owner, prToMerge.repo, prToMerge.number).then(result => {
    if (!result.success) {
      loadStage4() // Reload on failure
    }
  })
}

function removePRFromList(repo, prNumber) {
  stage4Data = stage4Data.filter(pr => !(pr.repo === repo && pr.number === prNumber))
  const readyPrs = stage4Data.filter(pr => isPRReady(pr))
  document.getElementById('stage4-count').textContent = readyPrs.length
  renderStage4(stage4Data)
}

// ============ PR Navigation ============
function updatePRNav() {
  const readyPrs = stage4Data.filter(pr => isPRReady(pr))
  const total = readyPrs.length

  document.getElementById('prCounter').textContent =
    total > 0 ? `${currentPRIndex + 1}/${total}` : '0/0'
  document.getElementById('prevPRBtn').disabled = currentPRIndex <= 0
  document.getElementById('nextPRBtn').disabled = currentPRIndex >= total - 1
}

function showNextPR() {
  const readyPrs = stage4Data.filter(pr => isPRReady(pr))
  if (readyPrs.length === 0) {
    bootstrap.Modal.getInstance(document.getElementById('prModal'))?.hide()
    log('✓ All PRs reviewed!', 'success')
    return
  }

  // Clamp index to valid range
  if (currentPRIndex >= readyPrs.length) currentPRIndex = readyPrs.length - 1

  const pr = readyPrs[currentPRIndex]
  showPRDetails(pr.repo, pr.number)
}

function showPrevPR() {
  const readyPrs = stage4Data.filter(pr => isPRReady(pr))
  if (currentPRIndex > 0) {
    currentPRIndex--
    const pr = readyPrs[currentPRIndex]
    showPRDetails(pr.repo, pr.number)
  }
}
