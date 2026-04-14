"""Two-layer upstream-ref sanitizer.

Replaces the jade-hare-era `backend.services.oss_firewall._sanitize_upstream_refs`
with a sanitizer that operates at both ends of the pipeline:

1. `scrub_brief(brief, upstream_slug, issue_number)` — **input-side**
   Strips real upstream URLs, slash-form short refs, bare upstream slugs,
   and identifying issue numbers from the aggregator brief BEFORE it is
   handed to the agent. Runs at the `eligible → forked` transition.
   Returns `(scrubbed_text, ScrubReport)`.

2. `scan_outputs(pr_title, pr_body, commit_messages, upstream_slug, issue_number)`
   — **output-side**
   Scans the proposed upstream PR title, body, and every commit message for
   any surviving real upstream ref. Runs at the `submittable → submitted`
   transition. Raises `SanitizerError` on any leak — blocks the upstream PR
   open. Hallucinated refs (numbers/slugs that don't match the recorded
   upstream identity) are tolerated as cosmetic noise.

See `docs/crimson-kitty/cross-ref-isolation.md` for the full threat model.

Phase 1B.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .evidence.scanner import (
    Leak,
    scan_commit_messages,
    scan_for_bare_slug,
    scan_for_keyword_ref,
    scan_for_short_ref,
    scan_for_url,
)


class SanitizerError(Exception):
    """Raised when `scan_outputs` finds any real upstream ref in outbound text.

    The exception's `leaks` attribute carries the list of detected `Leak`
    records so the caller (the `submittable → submitted` activity) can
    write them into the evidence store and surface them in the inbox.
    """

    def __init__(self, message: str, leaks: list[Leak] | None = None) -> None:
        super().__init__(message)
        self.leaks: list[Leak] = list(leaks or [])


# ── ScrubReport ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Substitution:
    pattern: str        # "url" | "short_ref" | "bare_slug" | "keyword_ref"
    matched: str        # the original substring that was replaced
    span: tuple[int, int]  # span in the ORIGINAL text (pre-scrub)
    replacement: str    # what replaced it


@dataclass
class ScrubReport:
    substitutions: list[Substitution] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.substitutions)

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "substitutions": [
                {
                    "pattern": s.pattern,
                    "matched": s.matched,
                    "span": list(s.span),
                    "replacement": s.replacement,
                }
                for s in self.substitutions
            ],
        }


# ── scrub_brief ───────────────────────────────────────────────────────────

# Replacement tokens used by scrub_brief. Chosen to be neutral, human-readable,
# and distinct enough that the agent doesn't pattern-complete them back into
# upstream refs.
_REPL_URL = "[upstream issue URL]"
_REPL_SHORT_REF = "[upstream issue]"
_REPL_BARE_SLUG = "the upstream project"
_REPL_KEYWORD_PHRASE = "[fix-keyword removed]"


def _url_pat(slug: str) -> re.Pattern[str]:
    return re.compile(
        r"(?ix)"
        r"\b(?:https?://)?"
        r"github\.com/" + re.escape(slug) + r"/"
        r"(?:issues|pull)/\d+"
        r"(?:[#?][\w-]+)?"
    )


def _short_ref_pat(slug: str) -> re.Pattern[str]:
    return re.compile(r"(?i)\b" + re.escape(slug) + r"#\d+\b")


def _bare_slug_pat(slug: str) -> re.Pattern[str]:
    return re.compile(
        r"(?i)(?<![\w./])" + re.escape(slug) + r"(?![\w/#-])"
    )


def _keyword_pat(issue_number: int | str, slug: str) -> re.Pattern[str]:
    """Match `Fixes #<n>` / `Closes <slug>#<any>` / etc."""
    kw_alt = "|".join((
        "close", "closes", "closed",
        "fix", "fixes", "fixed",
        "resolve", "resolves", "resolved",
    ))
    n = re.escape(str(issue_number))
    slug_re = re.escape(slug)
    return re.compile(
        r"(?i)\b(?:" + kw_alt + r")\s*:?\s*"
        r"(?:" + slug_re + r"#\d+|#" + n + r")\b"
    )


def scrub_brief(
    brief: str,
    upstream_slug: str,
    issue_number: int | str,
) -> tuple[str, ScrubReport]:
    """Strip every real upstream ref from `brief`.

    Order matters: keyword phrases (`Fixes #N`) are removed first, before
    the bare-slug pass would otherwise rewrite the slug inside them. URLs
    are next so their slugs aren't double-counted. Then short refs, then
    bare slugs.

    Returns the scrubbed text and a `ScrubReport` with one record per
    substitution. `scrubbed_text` is safe to pass to the agent: it
    contains zero real upstream refs.
    """
    if not brief:
        return brief, ScrubReport()

    if not upstream_slug:
        # Nothing to scrub against — return as-is. This is a programming
        # error at the call site; the caller should always know the slug.
        return brief, ScrubReport()

    report = ScrubReport()

    def _replace(text: str, pattern: re.Pattern[str], kind: str, replacement: str) -> str:
        # Walk matches in reverse so spans into `text` stay valid as we
        # rewrite. Spans recorded in the report refer to positions in the
        # ORIGINAL text passed in (we walk a snapshot for span recording).
        out = text
        for m in list(pattern.finditer(text))[::-1]:
            report.substitutions.append(Substitution(
                pattern=kind,
                matched=m.group(0),
                span=m.span(),
                replacement=replacement,
            ))
            out = out[:m.start()] + replacement + out[m.end():]
        return out

    # 1. Keyword phrases first — they contain `#N` or `slug#N` which would
    #    otherwise be matched by the short-ref / bare-slug passes below and
    #    counted twice.
    scrubbed = _replace(
        brief,
        _keyword_pat(issue_number, upstream_slug),
        "keyword_ref",
        _REPL_KEYWORD_PHRASE,
    )

    # 2. URLs.
    scrubbed = _replace(
        scrubbed,
        _url_pat(upstream_slug),
        "url",
        _REPL_URL,
    )

    # 3. Slash-form short refs.
    scrubbed = _replace(
        scrubbed,
        _short_ref_pat(upstream_slug),
        "short_ref",
        _REPL_SHORT_REF,
    )

    # 4. Bare slug. The bare-slug regex has lookahead/lookbehind that
    #    excludes slug-followed-by-`#` and slug-followed-by-`-`, so it
    #    won't double-fire on any of the above forms.
    scrubbed = _replace(
        scrubbed,
        _bare_slug_pat(upstream_slug),
        "bare_slug",
        _REPL_BARE_SLUG,
    )

    return scrubbed, report


# ── scan_outputs ──────────────────────────────────────────────────────────


def scan_outputs(
    pr_title: str,
    pr_body: str,
    commit_messages: list[dict],
    upstream_slug: str,
    issue_number: int | str,
) -> None:
    """Block submission if any real upstream ref appears in outbound text.

    Runs at the `submittable → submitted` transition. Hallucinated refs
    (numbers that don't match `issue_number`, slugs that don't match
    `upstream_slug`) are NOT flagged — they don't fire cross-references
    because there's nothing real to link to.

    Raises `SanitizerError` with the list of leaks attached on failure.
    On success, returns `None` (the caller proceeds to open the upstream PR).

    `commit_messages` is a list of `{sha, message}` dicts.
    """
    leaks: list[Leak] = []

    # Title + body get all four scanners.
    for source, text in (("pr_title", pr_title or ""), ("pr_body", pr_body or "")):
        leaks += scan_for_url(text, upstream_slug, source=source)
        leaks += scan_for_short_ref(text, upstream_slug, source=source)
        leaks += scan_for_bare_slug(text, upstream_slug, source=source)
        leaks += scan_for_keyword_ref(text, issue_number, upstream_slug, source=source)

    # Each commit message gets all four via the aggregator.
    leaks += scan_commit_messages(commit_messages or [], upstream_slug, issue_number)

    if leaks:
        kinds = sorted({l.kind for l in leaks})
        sources = sorted({l.source for l in leaks})
        raise SanitizerError(
            f"upstream ref leak(s) in outbound text: "
            f"{len(leaks)} leak(s) of kind(s) {kinds} in source(s) {sources}",
            leaks=leaks,
        )
