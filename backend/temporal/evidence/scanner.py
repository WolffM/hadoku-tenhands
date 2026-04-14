"""Cross-reference leak scanner.

Scans text for upstream-issue references that would fire a GitHub
cross-reference notification on the upstream issue when committed/pushed
to a fork. Used by:

  - the `input_context_clean` gate (scans the scrubbed brief at the
    `forked` state — verifies input scrubbing actually worked)
  - the `no_upstream_refs` gate (scans the upstream PR title, body, and
    every commit message at the `submitted` state — defense in depth)

See docs/crimson-kitty/cross-ref-isolation.md for the threat model and
the leak vectors we're closing.

The four scan functions return a list of `Leak` records. Empty list
means clean. Each Leak captures the matched substring, its position,
and which scanner caught it — useful for evidence + debugging.

Phase 1A.6.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Leak:
    kind: str          # "url" | "short_ref" | "keyword_ref" | "bare_slug"
    matched: str
    span: tuple[int, int]
    source: str = ""   # e.g. "commit:abc123" or "pr_body"


# ── URL form: https://github.com/owner/repo/issues|pull/N ─────────────────


def _url_re(slug: str) -> re.Pattern[str]:
    """Match full GitHub URLs targeting `slug`'s issues or pulls.

    Catches:
      https://github.com/microsoft/markitdown/issues/183
      https://github.com/microsoft/markitdown/pull/183
      http://github.com/microsoft/markitdown/issues/183
      github.com/microsoft/markitdown/issues/183  (no scheme)
      with optional fragments like #issuecomment-456
    """
    quoted = re.escape(slug)
    return re.compile(
        r"(?ix)"                                 # case-insensitive, verbose
        r"\b(?:https?://)?"
        r"github\.com/" + quoted + r"/"
        r"(?:issues|pull)/\d+"
        r"(?:[#?][\w-]+)?"
    )


def scan_for_url(text: str, upstream_slug: str, source: str = "") -> list[Leak]:
    if not text or not upstream_slug:
        return []
    return [
        Leak(kind="url", matched=m.group(0), span=m.span(), source=source)
        for m in _url_re(upstream_slug).finditer(text)
    ]


# ── Short ref form: owner/repo#N ──────────────────────────────────────────


def _short_ref_re(slug: str) -> re.Pattern[str]:
    """Match `owner/repo#N` references to `slug`, case-insensitive."""
    return re.compile(r"(?i)\b" + re.escape(slug) + r"#\d+\b")


def scan_for_short_ref(text: str, upstream_slug: str, source: str = "") -> list[Leak]:
    if not text or not upstream_slug:
        return []
    return [
        Leak(kind="short_ref", matched=m.group(0), span=m.span(), source=source)
        for m in _short_ref_re(upstream_slug).finditer(text)
    ]


# ── Bare upstream slug ────────────────────────────────────────────────────


def _slug_re(slug: str) -> re.Pattern[str]:
    """Match the bare slug as a word — `microsoft/markitdown` standalone.

    Boundary rules:
      - Preceding char cannot be a word char, dot, or slash (avoids matching
        in URL paths or longer slugs)
      - Following char cannot be a word char, slash, hyphen, or `#` (avoids
        matching prefixes of longer names like `markitdown-fork` or short
        refs like `markitdown#183`)
    """
    return re.compile(
        r"(?i)(?<![\w./])" + re.escape(slug) + r"(?![\w/#-])"
    )


def scan_for_bare_slug(text: str, upstream_slug: str, source: str = "") -> list[Leak]:
    if not text or not upstream_slug:
        return []
    leaks: list[Leak] = []
    # Skip matches that are part of a github.com URL — those are caught
    # by scan_for_url and we don't want to double-count.
    url_spans = [m.span() for m in _url_re(upstream_slug).finditer(text)]
    for m in _slug_re(upstream_slug).finditer(text):
        s, e = m.span()
        if any(us <= s and e <= ue for us, ue in url_spans):
            continue
        leaks.append(
            Leak(kind="bare_slug", matched=m.group(0), span=(s, e), source=source)
        )
    return leaks


# ── Keyword ref form: Fixes/Closes/Resolves #N (specific issue number) ────

# Auto-close keywords per GitHub docs:
#   https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
_AUTOCLOSE_KEYWORDS = (
    "close", "closes", "closed",
    "fix", "fixes", "fixed",
    "resolve", "resolves", "resolved",
)


def _keyword_re(issue_number: int | str, slug: str | None = None) -> re.Pattern[str]:
    """Match `Fixes #<issue_number>` (and slug-prefixed variants).

    If `slug` is provided, also catches `Fixes microsoft/markitdown#N` for
    any N (because the slash-form is unambiguously upstream).
    """
    kw_alt = "|".join(_AUTOCLOSE_KEYWORDS)
    n = re.escape(str(issue_number))

    if slug:
        slug_re = re.escape(slug)
        return re.compile(
            r"(?i)\b(?:" + kw_alt + r")\s*:?\s*"
            r"(?:" + slug_re + r"#\d+|#" + n + r")\b"
        )
    return re.compile(
        r"(?i)\b(?:" + kw_alt + r")\s*:?\s*#" + n + r"\b"
    )


def scan_for_keyword_ref(
    text: str,
    issue_number: int | str,
    upstream_slug: str | None = None,
    source: str = "",
) -> list[Leak]:
    if not text or issue_number is None:
        return []
    return [
        Leak(kind="keyword_ref", matched=m.group(0), span=m.span(), source=source)
        for m in _keyword_re(issue_number, upstream_slug).finditer(text)
    ]


# ── Commit message scanning ───────────────────────────────────────────────


def scan_commit_messages(
    commits: Iterable[dict],
    upstream_slug: str,
    issue_number: int | str,
) -> list[Leak]:
    """Scan a list of commit dicts for any leak form.

    Each commit is expected to have at least `{message: str, sha: str}`.
    Returns a flat list of leaks across all commits, with `source="commit:<sha>"`.
    """
    leaks: list[Leak] = []
    for c in commits:
        msg = c.get("message", "") if isinstance(c, dict) else ""
        sha = c.get("sha", "?") if isinstance(c, dict) else "?"
        source = f"commit:{sha}"
        leaks += scan_for_url(msg, upstream_slug, source=source)
        leaks += scan_for_short_ref(msg, upstream_slug, source=source)
        leaks += scan_for_bare_slug(msg, upstream_slug, source=source)
        leaks += scan_for_keyword_ref(msg, issue_number, upstream_slug, source=source)
    return leaks
