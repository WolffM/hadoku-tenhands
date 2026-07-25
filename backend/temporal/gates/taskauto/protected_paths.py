"""G6 — `protected_paths_untouched`.

There is no human between this agent and `main`, so a deny-list of paths
that never auto-merge is one of the few things standing between an agent's
diff and production. It matters most for the paths where "reversible by a
follow-up commit" stops being true: a leaked secret is burned the moment
it's pushed, a run migration doesn't un-run, and a broken deploy workflow
can break the mechanism that would ship the revert.

The override is `allow-protected:`, and where it may be read from is the
whole security property — see `task_text.extract_allow_protected`.
"""

from __future__ import annotations

import fnmatch

from .. import TASK_AUTOMATION, Fail, GateResult, Pass, gate
from ...taskauto.task_text import extract_allow_protected


def _matches(path: str, pattern: str) -> bool:
    """Glob match with `**` meaning "at any depth".

    `fnmatch` alone is not enough: its `*` happily crosses `/`, so
    `deploy/**` and `deploy/*` behave identically and a pattern like
    `**/migrations/**` never matches a top-level `migrations/`. Both
    directions of that error are dangerous here — one over-blocks and
    annoys, the other silently lets a protected path through.
    """
    # `lstrip("./")` would be a character-set strip, not a prefix strip:
    # it turns ".github/workflows/deploy.yml" into "github/..." and
    # ".devvault.json" into "devvault.json", so every dotfile on the
    # deny-list silently stops matching. Under-blocking is the dangerous
    # direction here, so remove exactly the "./" prefix and nothing else.
    while path.startswith("./"):
        path = path[2:]
    if fnmatch.fnmatch(path, pattern):
        return True
    if "**/" in pattern:
        # `**/x` must also match a top-level `x`.
        if fnmatch.fnmatch(path, pattern.replace("**/", "", 1)):
            return True
    if pattern.endswith("/**"):
        prefix = pattern[: -len("/**")]
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def protected_hits(paths, patterns) -> list[tuple[str, str]]:
    """Every (path, pattern) pair that the deny-list catches."""
    hits: list[tuple[str, str]] = []
    for p in paths:
        for pat in patterns:
            if _matches(p, pat):
                hits.append((p, pat))
                break
    return hits


@gate(pipeline=TASK_AUTOMATION, after="fixed", kind="mechanical")
def protected_paths_untouched(task, evidence) -> GateResult:
    """Fail if the diff touches a protected path without authorisation."""
    try:
        raw = evidence.read_text("05-fixed/files_touched.txt")
    except Exception as e:
        # Cannot see what changed. For a gate whose job is to bound an
        # unreviewed merge, "I don't know" is a failure, never a pass.
        return Fail(f"could not read files_touched.txt: {type(e).__name__}: {e}")

    paths = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not paths:
        # diff_non_empty (G4) owns the empty-diff case and will have failed
        # already; nothing here is protected, so don't double-report.
        return Pass("no files touched")

    policy = getattr(task, "policy", None)
    patterns = tuple(getattr(policy, "protected_paths", ()) or ())
    hits = protected_hits(paths, patterns)
    if not hits:
        return Pass(f"{len(paths)} file(s), none protected")

    allowed = extract_allow_protected(
        title=getattr(task, "title", "") or "",
        notes_at_claim=getattr(task, "notes_at_claim", "") or "",
    )
    unauthorised = [
        (p, pat) for p, pat in hits
        if not any(_matches(p, a) for a in allowed)
    ]
    if not unauthorised:
        return Pass(
            f"{len(hits)} protected path(s) touched, all authorised",
            evidence_data={"authorised": [p for p, _ in hits],
                           "allow_protected": allowed},
        )

    listed = ", ".join(f"{p} (matches {pat})" for p, pat in unauthorised[:5])
    return Fail(
        f"{len(unauthorised)} protected path(s) touched without "
        f"`allow-protected:` authorisation: {listed}",
        evidence_data={
            "unauthorised": [p for p, _ in unauthorised],
            "allow_protected": allowed,
        },
    )
