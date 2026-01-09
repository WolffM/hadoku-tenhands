/* VibeDispatch Shared Utility Functions */

/**
 * Format a date string as relative time (e.g., "2h ago", "3d ago")
 * @param {string} dateString - ISO date string
 * @returns {string} Formatted relative time
 */
function formatTimeAgo(dateString) {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);
    
    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800) return `${Math.floor(seconds / 86400)}d ago`;
    return date.toLocaleDateString();
}

/**
 * Escape HTML special characters to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Show a Bootstrap toast notification
 * @param {string} title - Toast title
 * @param {string} message - Toast message
 * @param {string} type - Toast type: 'success', 'error', or 'info'
 */
function showToast(title, message, type = 'success') {
    const toast = document.getElementById('toast');
    const toastTitle = document.getElementById('toast-title');
    const toastBody = document.getElementById('toast-body');
    const toastIcon = document.getElementById('toast-icon');
    
    toastTitle.textContent = title;
    toastBody.textContent = message;
    
    toastIcon.className = 'bi me-2';
    if (type === 'success') {
        toastIcon.classList.add('bi-check-circle-fill', 'text-success');
    } else if (type === 'error') {
        toastIcon.classList.add('bi-x-circle-fill', 'text-danger');
    } else if (type === 'info') {
        toastIcon.classList.add('bi-info-circle-fill', 'text-info');
    }
    
    const bsToast = new bootstrap.Toast(toast);
    bsToast.show();
}

/**
 * Get admin key from URL query parameters
 * @returns {string|null} Admin key if present
 */
function getAdminKey() {
    const params = new URLSearchParams(window.location.search);
    return params.get('key');
}

/**
 * Make an API call with loading state and toast notifications
 * @param {string} endpoint - API endpoint URL (will be prefixed with URL_PREFIX)
 * @param {object} data - Request body data
 * @param {HTMLElement} button - Optional button to show loading state
 * @returns {Promise<object>} API response
 */
async function apiCall(endpoint, data, button = null) {
    if (button) {
        button.classList.add('loading');
        button.disabled = true;
    }

    // Prepend URL prefix for deployment behind edge-router
    const url = (window.URL_PREFIX || '') + endpoint;

    // Include admin key in headers for edge-router authentication
    const headers = {
        'Content-Type': 'application/json'
    };
    const adminKey = getAdminKey();
    if (adminKey) {
        headers['X-User-Key'] = adminKey;
    }

    try {
        const response = await fetch(url, {
            method: 'POST',
            headers,
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        // Only show toast for explicit messages, not for data-fetching calls
        if (result.message) {
            showToast('Success', result.message, 'success');
        } else if (result.error && !result.success) {
            showToast('Error', result.error, 'error');
        }
        
        return result;
    } catch (error) {
        showToast('Error', 'An unexpected error occurred', 'error');
        return { success: false, error: error.message };
    } finally {
        if (button) {
            button.classList.remove('loading');
            button.disabled = false;
        }
    }
}

/**
 * Log a message to the progress log panel
 * @param {string} message - Message to log
 * @param {string} type - Message type: 'info', 'success', or 'error'
 */
function log(message, type = 'info') {
    const logEl = document.getElementById('progress-log');
    if (!logEl) return;
    
    const time = new Date().toLocaleTimeString();
    const typeClass = type === 'success' ? 'log-success' : type === 'error' ? 'log-error' : '';
    
    // Remove placeholder text if present
    const placeholder = logEl.querySelector('.text-secondary');
    if (placeholder) placeholder.remove();
    
    const entry = document.createElement('div');
    entry.className = `log-entry ${typeClass}`;
    entry.innerHTML = `<span class="log-time">[${time}]</span> ${escapeHtml(message)}`;
    logEl.appendChild(entry);
    logEl.scrollTop = logEl.scrollHeight;
}

/**
 * Clear the progress log
 */
function clearLog() {
    const logEl = document.getElementById('progress-log');
    if (!logEl) return;
    logEl.innerHTML = '<p class="text-secondary">Actions will be logged here...</p>';
}

/**
 * Get severity level from issue labels
 * @param {object} issue - Issue object with labels array
 * @returns {string} Severity level: 'critical', 'high', 'medium', or 'low'
 */
function getSeverity(issue) {
    const labels = issue.labels.map(l => l.name.toLowerCase());
    if (labels.some(l => l.includes('severity:critical'))) return 'critical';
    if (labels.some(l => l.includes('severity:high'))) return 'high';
    if (labels.some(l => l.includes('severity:medium'))) return 'medium';
    return 'low';
}

/**
 * Get CSS class for severity level
 * @param {string} severity - Severity level
 * @returns {string} CSS class name
 */
function getSeverityClass(severity) {
    return severity === 'critical' ? 'severity-critical' : 
           severity === 'high' ? 'severity-high' : 
           severity === 'medium' ? 'severity-medium' : 'severity-low';
}

/**
 * Render a diff string as syntax-highlighted HTML
 * @param {string} diff - Git diff string
 * @returns {string} HTML string
 */
function renderDiff(diff) {
    if (!diff) return '<p class="text-secondary">No changes</p>';
    
    const lines = diff.split('\n');
    let html = '';
    let currentFile = '';
    let inHunk = false;
    
    for (const line of lines) {
        if (line.startsWith('diff --git')) {
            const match = line.match(/b\/(.+)$/);
            currentFile = match ? match[1] : 'unknown';
            const fileId = currentFile.replace(/[^a-zA-Z0-9]/g, '-');
            if (html) html += '</pre></div>';
            html += `
                <div class="diff-file mb-3" id="diff-${fileId}">
                    <div class="diff-header bg-secondary bg-opacity-25 px-3 py-2 border-bottom border-secondary">
                        <strong class="text-light">${escapeHtml(currentFile)}</strong>
                    </div>
                    <pre class="diff-content m-0 p-0" style="font-size: 12px; line-height: 1.4;">`;
            inHunk = false;
        } else if (line.startsWith('@@')) {
            html += `<div class="diff-hunk bg-primary bg-opacity-10 px-3 py-1 text-info">${escapeHtml(line)}</div>`;
            inHunk = true;
        } else if (inHunk) {
            let lineClass = 'diff-line px-3';
            if (line.startsWith('+')) {
                lineClass += ' diff-add';
            } else if (line.startsWith('-')) {
                lineClass += ' diff-del';
            } else {
                lineClass += ' diff-context';
            }
            html += `<div class="${lineClass}">${escapeHtml(line) || ' '}</div>`;
        }
    }
    
    if (html) html += '</pre></div>';
    
    return html || '<p class="text-secondary">No changes to display</p>';
}

// ============ Selection Helpers ============

/**
 * Select all checkboxes matching a selector
 * @param {string} selector - CSS selector for checkboxes
 */
function selectAll(selector) {
    document.querySelectorAll(selector).forEach(cb => cb.checked = true);
}

/**
 * Deselect all checkboxes matching a selector
 * @param {string} selector - CSS selector for checkboxes
 */
function selectNone(selector) {
    document.querySelectorAll(selector).forEach(cb => cb.checked = false);
}

/**
 * Get values of all checked checkboxes matching a selector
 * @param {string} selector - CSS selector for checkboxes
 * @returns {string[]} Array of checkbox values
 */
function getSelectedValues(selector) {
    return Array.from(document.querySelectorAll(`${selector}:checked`)).map(cb => cb.value);
}

// ============ UI Helpers ============

/**
 * Generate a loading spinner HTML
 * @param {string} message - Optional message to display
 * @returns {string} HTML string
 */
function loadingSpinner(message = '') {
    return `<div class="text-center py-4">
        <div class="spinner-border text-primary"></div>
        ${message ? `<p class="text-secondary mt-2">${escapeHtml(message)}</p>` : ''}
    </div>`;
}

/**
 * Generate a status badge HTML
 * @param {string} status - Status string
 * @returns {string} HTML string with appropriate badge class
 */
function getStatusBadge(status) {
    const statusLower = (status || '').toLowerCase();
    let badgeClass = 'bg-secondary';
    
    if (statusLower === 'success') badgeClass = 'bg-success';
    else if (statusLower === 'failure' || statusLower === 'error') badgeClass = 'bg-danger';
    else if (statusLower === 'in_progress' || statusLower === 'triggered') badgeClass = 'bg-info';
    else if (statusLower === 'pending' || statusLower === 'queued') badgeClass = 'bg-warning';
    
    return `<span class="badge ${badgeClass}">${escapeHtml(status || 'unknown')}</span>`;
}

/**
 * Run a batch operation on selected items with logging
 * @param {string[]} items - Array of items to process
 * @param {function} operation - Async function(item) to run on each item
 * @param {object} options - Options: { itemLabel, successMsg, errorMsg }
 * @returns {Promise<string[]>} Array of successful items
 */
async function batchOperation(items, operation, options = {}) {
    const { itemLabel = 'item', onSuccess, onError } = options;
    const successful = [];
    
    for (const item of items) {
        const result = await operation(item);
        if (result && result.success) {
            successful.push(item);
            if (onSuccess) onSuccess(item, result);
        } else {
            if (onError) onError(item, result);
        }
    }
    
    return successful;
}

/**
 * Disable/enable UI during batch operations
 * @param {string} buttonSelector - Selector for the action button
 * @param {string} checkboxSelector - Selector for checkboxes to disable
 * @param {boolean} disabled - Whether to disable
 * @param {string} loadingText - Text to show on button when disabled
 */
function setBatchUIState(buttonSelector, checkboxSelector, disabled, loadingText = 'Processing...') {
    const btn = document.querySelector(buttonSelector);
    if (btn) {
        btn.disabled = disabled;
        if (disabled) {
            btn.dataset.originalHtml = btn.innerHTML;
            btn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> ${loadingText}`;
        } else if (btn.dataset.originalHtml) {
            btn.innerHTML = btn.dataset.originalHtml;
        }
    }
    
    if (checkboxSelector) {
        document.querySelectorAll(checkboxSelector).forEach(cb => cb.disabled = disabled);
    }
}

