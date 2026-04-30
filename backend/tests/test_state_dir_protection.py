"""Guard against the 2026-04-28 state-wipe incident.

The prior `.gitignore` enumerated `state/` patterns per-batch
(`smoke-*`, `batch-*`, `crimson-kitty-*`, `phase4-external-v*`).
Phase 5 batches weren't covered — `state/phase5-prod-v*/` was
untracked-but-not-ignored.

`hadoku_site`'s deploy-executor runs `git stash --include-untracked`
before pulling main and never pops the stash. Untracked files get
stashed and disappear from disk; ignored files are skipped by stash.
On 2026-04-28 the entire phase5 batch evidence (inbox entries,
gates.jsonl, transitions.jsonl, rendered PR bodies) was wiped during
a deploy because the patterns were too narrow.

The current `.gitignore` uses `state/*/` to catch ALL state subdirs
generically. This test asserts that invariant holds against future
edits — if someone removes the catch-all and reverts to per-batch
enumeration, this test fails before the deploy-time wipe re-bites.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _check_ignored(path: str) -> bool:
    """True if `path` is ignored per the repo's `.gitignore` rules.

    Uses `git check-ignore` (exit 0 = ignored, exit 1 = not ignored).
    """
    result = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "check-ignore", "-q", path],
        capture_output=True,
    )
    return result.returncode == 0


def test_arbitrary_state_subdirs_are_gitignored():
    """Any new directory created under `state/` must be gitignored.

    This is the invariant that protects against deploy-time stash sweeps.
    Verifies the actual git-side behavior, not just the file contents,
    so the test catches typos / pattern-shape mistakes that would parse
    OK in `.gitignore` but not actually ignore the path.
    """
    sample_paths = [
        # The exact name shape from the 2026-04-28 incident
        "state/phase5-prod-v1-20260427-2254/",
        # Future phases (must keep working as the phase counter advances)
        "state/phase6-prod-v1/",
        "state/phase7-experimental/",
        # Arbitrary names that don't match any historic enumeration —
        # the catch-all must protect these too
        "state/some-arbitrary-batch/",
        "state/2026-12-31-canary/",
        "state/operator-driven-name/",
    ]
    failures = [p for p in sample_paths if not _check_ignored(p)]
    assert not failures, (
        f"state/ subdirs not gitignored: {failures} — see "
        f".gitignore comment block at the state/ section. The catch-all "
        f"`state/*/` pattern must remain in place to survive deploy-time "
        f"`git stash --include-untracked` sweeps."
    )


def test_gitignore_state_pattern_is_a_catch_all_not_an_enumeration():
    """The `.gitignore` should catch state subdirs by pattern, not by
    listing each batch type explicitly.

    Per-batch enumeration is what caused the 2026-04-28 wipe — phase5
    wasn't in the list. A catch-all (`state/*/`) is the safe shape.
    """
    gitignore = (_REPO_ROOT / ".gitignore").read_text()
    assert "state/*/" in gitignore, (
        "Expected `state/*/` catch-all in .gitignore but didn't find it. "
        "If the pattern was renamed, update this test. If it was removed, "
        "see the comment block in .gitignore for why this matters."
    )
