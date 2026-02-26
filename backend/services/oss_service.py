"""
OSS Service — core business logic for the OSS contribution pipeline.

Aggregator API communication, module-level helpers, and the composed
OSSService class. Fork management, local state, and context building
are in separate mixin modules (oss_fork, oss_state, oss_context).
"""

import os
import re
import json
import requests

from .cache import CACHE_DIR

# ============ Helpers ============


def _parse_jsonl(text):
    """Parse JSONL output (one JSON object per line) into a list of dicts."""
    items = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return items


# ============ Constants ============

OSS_DATA_DIR = os.path.join(CACHE_DIR, "oss")
AGGREGATOR_API_URL = os.environ.get("AGGREGATOR_API_URL", "")

# Pattern: https://github.com/owner/repo/issues/123 or /pull/123
_GITHUB_ISSUE_URL_RE = re.compile(
    r'https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull)/\d+'
)
# Pattern: owner/repo#123  (but NOT standalone #123 which is fine on a fork)
_CROSS_REPO_REF_RE = re.compile(
    r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#\d+'
)
# Pattern: Closes/Fixes/Resolves #123 (GitHub auto-close keywords)
_AUTOCLOSE_RE = re.compile(
    r'\b(Closes?|Fixes?|Resolves?)\s+#\d+', re.IGNORECASE
)


# ============ Private Helpers ============

def _load_json(filename):
    """Load a JSON file from the OSS data directory. Returns [] if missing."""
    path = os.path.join(OSS_DATA_DIR, filename)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_json(filename, data):
    """Save data as JSON to the OSS data directory."""
    os.makedirs(OSS_DATA_DIR, exist_ok=True)
    path = os.path.join(OSS_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _call_aggregator(endpoint, method="GET", data=None, timeout=10):
    """Call aggregator API with graceful failure. Returns None on any error."""
    if not AGGREGATOR_API_URL:
        return None
    try:
        url = f"{AGGREGATOR_API_URL}{endpoint}"
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, json=data, timeout=timeout)
        if resp.ok:
            return resp.json()
        return None
    except Exception:
        return None


def _sanitize_upstream_refs(text):
    """Strip upstream GitHub references from text to prevent cross-linking.

    When we post issues on a fork, GitHub auto-creates cross-reference
    notifications on the upstream repo for any of these patterns:
    - Full URLs: https://github.com/owner/repo/issues/123
    - Cross-repo refs: owner/repo#123
    - Auto-close keywords: Closes #123, Fixes #123, Resolves #123

    This function neutralizes them so the fork work stays invisible to upstream.
    """
    if not text:
        return text
    # Replace full GitHub issue/PR URLs with plain text (no link)
    # e.g. https://github.com/reisepass/email-verifier/issues/4 → reisepass/email-verifier issue 4
    text = _GITHUB_ISSUE_URL_RE.sub(
        lambda m: m.group(0)
            .replace("https://github.com/", "")
            .replace("/issues/", " issue ")
            .replace("/pull/", " PR "),
        text
    )
    # Replace cross-repo refs: owner/repo#123 → owner/repo issue 123
    text = _CROSS_REPO_REF_RE.sub(
        lambda m: m.group(0).replace("#", " issue "),
        text
    )
    # Neutralize auto-close keywords: "Closes #4" → "Related to issue 4"
    text = _AUTOCLOSE_RE.sub(
        lambda m: "Related to issue " + m.group(0).split("#")[-1],
        text
    )
    return text


def _detect_tool_from_issue(issue_body):
    """Extract the detection tool name from a vibecheck issue body.

    vibecheck issues use a markdown table with a row like:
        | Tool | `ruff` |

    Returns the tool name (str) or None if not detected.
    """
    if not issue_body:
        return None
    # Match vibecheck table format: | Tool | `toolname` |
    match = re.search(r'\|\s*Tool\s*\|\s*`(\w[\w-]*)`', issue_body)
    if match:
        return match.group(1).lower()
    return None


# ============ OSSService ============

from .oss_state import OSSStateMixin
from .oss_fork import OSSForkMixin
from .oss_context import OSSContextMixin


class OSSService(OSSStateMixin, OSSForkMixin, OSSContextMixin):
    """Service layer for the OSS contribution pipeline.

    Composed from mixins:
    - OSSStateMixin: local JSON state (watchlist, assignments, etc.)
    - OSSForkMixin: fork management, CI/workflow setup, PR review helpers
    - OSSContextMixin: agent context building (3-tier strategy)
    """

    def __init__(self):
        self.data_dir = OSS_DATA_DIR

    # --- Aggregator API (proxied when available, returns empty/None otherwise) ---

    def get_watchlist(self):
        """Get the watchlist from the aggregator.

        Aggregator returns: { success: true, data: { slugs: [...] } }
        """
        result = _call_aggregator("/recon/watchlist")
        if not result or not isinstance(result, dict):
            return []
        # Unwrap: { success, data: { slugs: [...] } }
        data = result.get("data") or result
        if isinstance(data, dict) and "slugs" in data:
            return data["slugs"]
        if "slugs" in result:
            return result["slugs"]
        return []

    def add_to_watchlist(self, slug):
        """Add a repo to the aggregator watchlist. Stub — returns False."""
        result = _call_aggregator("/recon/watchlist/add", method="POST", data={"slug": slug})
        return result is not None

    def remove_from_watchlist(self, slug):
        """Remove a repo from the aggregator watchlist. Stub — returns False."""
        result = _call_aggregator("/recon/watchlist/remove", method="POST", data={"slug": slug})
        return result is not None

    def get_scored_issues(self, slug=None):
        """Get scored issues from the aggregator.

        Aggregator returns: { success: true, data: { issues: [...] } }
        When pre-computed data is missing: { success: true, data: { status: "pending" } }

        Returns list of issues, or [] if unavailable/pending.
        """
        if slug:
            result = _call_aggregator(f"/recon/{slug}/scored-issues")
        else:
            result = _call_aggregator("/recon/all-scored-issues")
        if not result:
            return []
        # Unwrap aggregator response: { success, data: { issues: [...] } }
        if isinstance(result, dict):
            data = result.get("data") or result
            # Check for pending status (pre-computed data not yet available)
            if isinstance(data, dict) and data.get("status") == "pending":
                return []
            issues = data.get("issues") if isinstance(data, dict) else None
            if isinstance(issues, list):
                return issues
        if isinstance(result, list):
            return result
        return []

    def get_dossier(self, slug):
        """Get a repo dossier from the aggregator.

        Aggregator returns: { success: true, data: { slug, sections: {...} } }
        When pre-computed data is missing: { success: true, data: { status: "pending" } }
        Callers expect: { slug, sections: {...} } (the inner data object), or None.
        """
        result = _call_aggregator(f"/recon/{slug}/dossier")
        if not result or not isinstance(result, dict):
            return None
        # Unwrap: { success, data: { ... } }
        if "data" in result and isinstance(result["data"], dict):
            data = result["data"]
            # Check for pending status
            if data.get("status") == "pending":
                return None
            return data
        return result

    def get_issue_brief(self, slug, issue_id):
        """Get a pre-built issue brief from the aggregator.

        Args:
            slug: Hyphenated repo slug (e.g., "fastify-fastify")
            issue_id: Issue identifier (e.g., "github-fastify-fastify-1234")

        Returns:
            dict with {issue, repoHealth, brief} or None if unavailable/pending.
        """
        result = _call_aggregator(f"/recon/{slug}/issue-brief/{issue_id}")
        if result and result.get("success") and result.get("data"):
            data = result["data"]
            # Check for pending status
            if isinstance(data, dict) and data.get("status") == "pending":
                return None
            return data
        return None

    def trigger_compute(self, slug):
        """Trigger pre-computation of scored issues, dossier, and briefs for a repo.

        The aggregator requires POST /:slug/compute to run before scored-issues,
        dossier, and issue-brief endpoints return data.
        """
        result = _call_aggregator(f"/recon/{slug}/compute", method="POST", timeout=30)
        return result is not None

    def trigger_refresh(self, slug):
        """Trigger a re-scrape for a repo."""
        result = _call_aggregator(f"/recon/{slug}/refresh", method="POST")
        return result is not None

    # --- Claim management ---

    def report_claim(self, origin_slug, issue_id, claimed_by, fork_issue_url):
        """Report a claim to the aggregator. Best-effort — doesn't fail if aggregator is down.

        NOTE: origin_slug is stored in slash format (owner/repo) for gh CLI compatibility.
        The aggregator API uses hyphenated format (owner-repo) for KV key compatibility.
        The conversion happens here — do not "fix" this by changing the stored format.
        """
        slug = origin_slug.replace("/", "-")
        _call_aggregator(f"/recon/{slug}/claim", method="POST", data={
            "issueId": issue_id,
            "claimedBy": claimed_by,
            "forkIssueUrl": fork_issue_url,
        })

    def report_unclaim(self, origin_slug, issue_id):
        """Report an unclaim to the aggregator. Best-effort.

        NOTE: See report_claim() for slug format convention.
        """
        slug = origin_slug.replace("/", "-")
        _call_aggregator(f"/recon/{slug}/unclaim", method="POST", data={
            "issueId": issue_id,
        })
