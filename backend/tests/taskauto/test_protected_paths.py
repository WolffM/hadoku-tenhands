"""Tests for G6 — protected_paths_untouched.

There is no human between the agent and `main`, so this gate is one of the
few things standing between a diff and production. The authorisation tests
are the ones that matter: an agent must not be able to grant itself access
to CI, the vault manifest, or its own gates.
"""

from __future__ import annotations

import pytest

from temporal.gates import TASK_AUTOMATION, registry_snapshot, run_gates
from temporal.gates.taskauto.protected_paths import (
    protected_hits,
    protected_paths_untouched,
)
from temporal.taskauto.refs import RepoPolicy, TaskRef


class Ev:
    """Minimal evidence stub: only files_touched.txt is read."""

    def __init__(self, files=None, *, explode=False):
        self.files = files
        self.explode = explode

    def read_text(self, path):
        assert path == "05-fixed/files_touched.txt"
        if self.explode:
            raise OSError("disk gone")
        return "\n".join(self.files or [])

    def write_json(self, *a, **k):
        pass


def ref(title="a task", notes="", policy=None):
    return TaskRef(
        repo_slug="WolffM/tenhands", board="h1", task_id="t1",
        title=title, notes_at_claim=notes,
        policy=policy or RepoPolicy(),
    )


def verdict(files, *, title="a task", notes="", policy=None):
    return protected_paths_untouched(ref(title, notes, policy), Ev(files))


# ── the deny-list ─────────────────────────────────────────────────────────


def test_ordinary_source_changes_pass():
    r = verdict(["backend/services/oss_service.py", "frontend/src/App.tsx"])
    assert r.verdict == "pass"


@pytest.mark.parametrize("path", [
    ".github/workflows/deploy.yml",
    "Dockerfile",
    "deploy/pm2.config.js",
    "infra/terraform/main.tf",
    ".devvault.json",
    ".env.local",
    "config/app_secrets.ts",
    "certs/server.pem",
    "db/migrations/0004_add_column.sql",
    "backend/temporal/gates/taskauto/protected_paths.py",
])
def test_protected_paths_are_blocked(path):
    r = verdict([path])
    assert r.verdict == "fail"
    assert path in r.reason


@pytest.mark.parametrize("path", [
    "package.json",
    "apps/ui/package.json",
    "pnpm-lock.yaml",
    "requirements.txt",
])
def test_manifests_are_no_longer_blocked_by_path(path):
    """They moved to `manifest_paths`, judged by content in
    `dependencies_unchanged` (G6b) and in `Lander.preflight`.

    A path rule could only ever answer "was it touched", and these are touched
    on nearly every task by a version bump — so it stalled almost everything
    and caught almost nothing. This gate must now let them by; the content
    rule is what refuses a dependency.
    """
    assert verdict([path]).verdict == "pass"


def test_the_gate_blocks_edits_to_its_own_gates():
    """An agent that can edit its own gates is not gated."""
    r = verdict(["backend/temporal/gates/taskauto/protected_paths.py"])
    assert r.verdict == "fail"


def test_one_protected_path_among_many_ordinary_ones_still_fails():
    r = verdict(["src/a.ts", "src/b.ts", ".github/workflows/deploy.yml"])
    assert r.verdict == "fail"
    assert r.evidence_data["unauthorised"] == [".github/workflows/deploy.yml"]


# ── glob semantics ────────────────────────────────────────────────────────


def test_double_star_matches_at_any_depth():
    """`**/migrations/**` must catch a top-level `migrations/` too —
    fnmatch alone silently misses that and lets the path through."""
    assert protected_hits(["migrations/001.sql"], ("**/migrations/**",))
    assert protected_hits(["a/b/migrations/001.sql"], ("**/migrations/**",))


def test_prefix_double_star_matches_the_directory_itself():
    assert protected_hits(["deploy"], ("deploy/**",))
    assert protected_hits(["deploy/x/y.sh"], ("deploy/**",))


def test_star_does_not_leak_across_directories_by_accident():
    """`.env*` should catch `.env.local`, not `src/env/config.ts`."""
    assert protected_hits([".env.local"], (".env*",))
    assert not protected_hits(["src/env/config.ts"], (".env*",))


def test_leading_dot_slash_is_normalised():
    assert protected_hits(["./Dockerfile"], ("Dockerfile",))


# ── authorisation ─────────────────────────────────────────────────────────


def test_allow_protected_in_the_title_authorises_that_path():
    r = verdict([".github/workflows/deploy.yml"],
                title="fix deploy allow-protected: .github/workflows/deploy.yml")
    assert r.verdict == "pass"
    assert r.evidence_data["allow_protected"] == [".github/workflows/deploy.yml"]


def test_allow_protected_in_the_claim_snapshot_authorises():
    r = verdict([".github/workflows/deploy.yml"],
                notes="allow-protected: .github/workflows/*.yml")
    assert r.verdict == "pass"


def test_authorisation_is_scoped_to_what_was_named():
    """Authorising the deploy workflow must not authorise the vault."""
    r = verdict([".github/workflows/deploy.yml", ".devvault.json"],
                title="allow-protected: .github/workflows/deploy.yml")
    assert r.verdict == "fail"
    assert r.evidence_data["unauthorised"] == [".devvault.json"]


def test_the_agents_own_notes_cannot_authorise_anything():
    """THE test. `notes_at_claim` is the snapshot from before we could
    write. Whatever the planning agent later put in live notes is not here,
    so it cannot grant itself CI or its own gates."""
    r = verdict(["backend/temporal/judge.py"],
                notes="the human's original request, no directive")
    assert r.verdict == "fail"


def test_prose_in_notes_does_not_authorise():
    r = verdict([".github/workflows/deploy.yml"],
                notes="we could add allow-protected: .github/workflows/** here")
    assert r.verdict == "fail"


# ── failure modes ─────────────────────────────────────────────────────────


def test_unreadable_evidence_fails_closed():
    """For a gate bounding an unreviewed merge, "I don't know what changed"
    is a failure, never a pass."""
    r = protected_paths_untouched(ref(), Ev(explode=True))
    assert r.verdict == "fail"
    assert "could not read" in r.reason


def test_empty_diff_is_not_this_gates_problem():
    """G4 (diff_non_empty) owns that case; double-reporting would send two
    different stall reasons for one fault."""
    assert protected_paths_untouched(ref(), Ev([])).verdict == "pass"


def test_empty_policy_blocks_nothing():
    r = verdict([".github/workflows/deploy.yml"],
                policy=RepoPolicy(protected_paths=()))
    assert r.verdict == "pass"


# ── registration ──────────────────────────────────────────────────────────


def test_registers_under_task_automation_only():
    """It must never fire for crimson-kitty, whose `fixed` state is a
    different pipeline's concern entirely."""
    entries = [
        (p, after, name) for p, after, _, name in registry_snapshot()
        if name == "protected_paths_untouched"
    ]
    assert entries == [(TASK_AUTOMATION, "fixed", "protected_paths_untouched")]


def test_runs_via_the_namespaced_registry():
    results = run_gates("fixed", ref(), Ev([".github/workflows/deploy.yml"]),
                        pipeline=TASK_AUTOMATION)
    names = [r.name for r in results]
    assert "protected_paths_untouched" in names
    assert all(r.verdict == "fail" for r in results
               if r.name == "protected_paths_untouched")


def test_crimson_kitty_never_runs_this_gate():
    results = run_gates("fixed", ref(), Ev([".github/workflows/deploy.yml"]),
                        pipeline="crimson-kitty")
    assert "protected_paths_untouched" not in [r.name for r in results]


@pytest.mark.parametrize("path,pattern", [
    (".github/workflows/deploy.yml", ".github/workflows/**"),
    (".devvault.json", ".devvault.json"),
    (".env.local", ".env*"),
    (".env", ".env*"),
])
def test_dotfiles_are_matched_not_silently_stripped(path, pattern):
    """Regression: an earlier version used `path.lstrip("./")`, which strips
    a CHARACTER SET rather than a prefix — so ".github/..." became
    "github/..." and every dotfile on the deny-list stopped matching. That
    fails in the dangerous direction: it under-blocks, silently."""
    assert protected_hits([path], (pattern,)) == [(path, pattern)]


def test_dot_slash_prefix_is_stripped_without_eating_the_dotfile():
    assert protected_hits(["./.devvault.json"], (".devvault.json",))
