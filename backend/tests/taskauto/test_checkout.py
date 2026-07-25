"""Tests for temporal/taskauto/checkout.py.

Most of these are about the *absence* of a local clone, or a local clone
that turns out to be unusable. "We've never cloned this repo" is the
ordinary path for any new repo added to the pipeline, and it must be
indistinguishable from normal operation apart from being slower.
"""

from __future__ import annotations

import pytest

from temporal.taskauto.checkout import (
    CheckoutError,
    CheckoutManager,
    RunResult,
    _normalise_remote,
)


class FakeGit:
    """Records commands; answers `remote get-url` and health checks."""

    def __init__(self, *, origins=None, fail=(), clone_creates=True):
        self.origins = origins or {}      # path -> origin url
        self.fail = fail                  # substrings of commands that fail
        self.clone_creates = clone_creates
        self.calls: list[list[str]] = []

    def __call__(self, args, cwd=None, timeout=600):
        args = list(args)
        self.calls.append(args)
        joined = " ".join(args)
        for pat in self.fail:
            if pat in joined:
                return RunResult(False, "", f"simulated failure: {pat}")
        if "remote" in args and "get-url" in args:
            path = args[2]
            if path in self.origins:
                return RunResult(True, self.origins[path] + "\n")
            return RunResult(False, "", "no such remote")
        if "clone" in args and self.clone_creates:
            from pathlib import Path
            dest = Path(args[-1])
            (dest / ".git").mkdir(parents=True, exist_ok=True)
        return RunResult(True, "")

    @property
    def clones(self):
        return [c for c in self.calls if "clone" in c]


def mgr(tmp_path, git, local_search=()):
    return CheckoutManager(root=tmp_path / "pipeline",
                           local_search=tuple(local_search), run=git)


def make_local(tmp_path, name, *, shallow=False):
    d = tmp_path / "repos" / name
    (d / ".git").mkdir(parents=True)
    if shallow:
        (d / ".git" / "shallow").write_text("deadbeef\n")
    return d


# ── remote normalisation ──────────────────────────────────────────────────


@pytest.mark.parametrize("url", [
    "https://github.com/WolffM/tenhands.git",
    "https://github.com/WolffM/tenhands",
    "git@github.com:WolffM/tenhands.git",
    "ssh://git@github.com/WolffM/tenhands.git",
    "https://github.com/WolffM/tenhands/",
])
def test_remote_forms_all_compare_equal(url):
    """Declining a perfectly good local reference over URL punctuation would
    be a silent, slow, and very confusing regression."""
    assert _normalise_remote(url) == "wolffm/tenhands"


def test_different_repos_do_not_compare_equal():
    assert _normalise_remote("https://github.com/WolffM/other") != "wolffm/tenhands"


# ── path mapping ──────────────────────────────────────────────────────────


def test_path_is_derived_mechanically_from_the_slug(tmp_path):
    m = mgr(tmp_path, FakeGit())
    assert m.path_for("WolffM/tenhands") == tmp_path / "pipeline" / "WolffM" / "tenhands"


@pytest.mark.parametrize("bad", ["", "tenhands", "/tenhands", "WolffM/"])
def test_a_missing_or_malformed_repo_says_where_it_comes_from(tmp_path, bad):
    """An unactivated board leaves `repo` empty, and that's the likeliest
    cause — the error should point there rather than at this function."""
    m = mgr(tmp_path, FakeGit())
    with pytest.raises(CheckoutError, match="board"):
        m.path_for(bad)


# ── no local clone: the ordinary path ─────────────────────────────────────


def test_no_local_clone_at_all_just_clones(tmp_path):
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    dest = m.ensure("WolffM/brand-new")
    assert dest.exists()
    assert git.clones == [["git", "clone",
                           "https://github.com/WolffM/brand-new.git", str(dest)]]
    assert "--reference-if-able" not in " ".join(git.clones[0])


def test_local_search_dir_does_not_exist(tmp_path):
    """A machine with no ~/repos at all must still work."""
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[tmp_path / "nope"])
    assert m.local_reference("WolffM/tenhands") is None
    assert m.ensure("WolffM/tenhands").exists()


def test_no_local_search_paths_configured(tmp_path):
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[])
    assert m.local_reference("WolffM/tenhands") is None
    assert m.ensure("WolffM/tenhands").exists()


# ── borrowing from a local clone ──────────────────────────────────────────


def test_matching_local_clone_is_borrowed_and_dissociated(tmp_path):
    local = make_local(tmp_path, "tenhands")
    git = FakeGit(origins={str(local): "https://github.com/WolffM/tenhands.git"})
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    dest = m.ensure("WolffM/tenhands")
    cmd = " ".join(git.clones[0])
    assert "--reference-if-able" in cmd and str(local) in cmd
    assert "--dissociate" in cmd, "borrowing must not leave a lasting link"
    assert dest.exists()


def test_scp_style_origin_still_matches(tmp_path):
    local = make_local(tmp_path, "tenhands")
    git = FakeGit(origins={str(local): "git@github.com:WolffM/tenhands.git"})
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    assert m.local_reference("WolffM/tenhands") == local


# ── local clones we must decline ──────────────────────────────────────────


def test_same_name_different_project_is_not_borrowed(tmp_path):
    """`~/repos/tenhands` could be somebody else's `tenhands`."""
    local = make_local(tmp_path, "tenhands")
    git = FakeGit(origins={str(local): "https://github.com/SomeoneElse/tenhands.git"})
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    assert m.local_reference("WolffM/tenhands") is None
    m.ensure("WolffM/tenhands")
    assert "--reference-if-able" not in " ".join(git.clones[0])


def test_directory_without_a_git_dir_is_not_borrowed(tmp_path):
    (tmp_path / "repos" / "tenhands").mkdir(parents=True)
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    assert m.local_reference("WolffM/tenhands") is None


def test_shallow_local_clone_is_not_borrowed(tmp_path):
    """A shallow repo may simply not have the objects, and git's failure mode
    is a confusing clone error rather than a clean miss."""
    local = make_local(tmp_path, "tenhands", shallow=True)
    git = FakeGit(origins={str(local): "https://github.com/WolffM/tenhands.git"})
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    assert m.local_reference("WolffM/tenhands") is None


def test_local_repo_that_cannot_report_its_origin_is_skipped(tmp_path):
    make_local(tmp_path, "tenhands")
    git = FakeGit(origins={})   # get-url fails
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    assert m.local_reference("WolffM/tenhands") is None


def test_first_matching_search_path_wins(tmp_path):
    a = tmp_path / "a" / "tenhands"; (a / ".git").mkdir(parents=True)
    b = tmp_path / "b" / "tenhands"; (b / ".git").mkdir(parents=True)
    git = FakeGit(origins={str(a): "https://github.com/WolffM/tenhands",
                           str(b): "https://github.com/WolffM/tenhands"})
    m = mgr(tmp_path, git, local_search=[tmp_path / "a", tmp_path / "b"])
    assert m.local_reference("WolffM/tenhands") == a


def test_a_later_search_path_is_used_when_the_first_mismatches(tmp_path):
    a = tmp_path / "a" / "tenhands"; (a / ".git").mkdir(parents=True)
    b = tmp_path / "b" / "tenhands"; (b / ".git").mkdir(parents=True)
    git = FakeGit(origins={str(a): "https://github.com/Other/tenhands",
                           str(b): "https://github.com/WolffM/tenhands"})
    m = mgr(tmp_path, git, local_search=[tmp_path / "a", tmp_path / "b"])
    assert m.local_reference("WolffM/tenhands") == b


# ── failure of the borrowed clone ─────────────────────────────────────────


def test_failed_reference_clone_retries_without_the_reference(tmp_path):
    """A local repo can be present and still unusable — mid-gc, corrupt,
    permissions. Falling back costs a slower clone; not falling back costs
    the whole task for no reason."""
    local = make_local(tmp_path, "tenhands")
    git = FakeGit(origins={str(local): "https://github.com/WolffM/tenhands"},
                  fail=("--reference-if-able",))
    m = mgr(tmp_path, git, local_search=[tmp_path / "repos"])
    dest = m.ensure("WolffM/tenhands")
    assert len(git.clones) == 2
    assert "--reference-if-able" in " ".join(git.clones[0])
    assert "--reference-if-able" not in " ".join(git.clones[1])
    assert dest.exists()


def test_clone_failing_outright_raises_with_the_git_error(tmp_path):
    git = FakeGit(fail=("clone",), clone_creates=False)
    m = mgr(tmp_path, git, local_search=[])
    with pytest.raises(CheckoutError, match="could not clone"):
        m.ensure("WolffM/tenhands")


# ── reuse and repair ──────────────────────────────────────────────────────


def test_existing_healthy_clone_is_reused_not_recloned(tmp_path):
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[])
    first = m.ensure("WolffM/tenhands")
    assert len(git.clones) == 1
    assert m.ensure("WolffM/tenhands") == first
    assert len(git.clones) == 1, "second call must not re-clone"


def test_broken_clone_is_replaced_rather_than_nursed(tmp_path):
    """It holds nothing a human would miss, so recloning is always right."""
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[])
    dest = m.ensure("WolffM/tenhands")
    (dest / ".git").rmdir()
    (dest / "leftover.txt").write_text("junk")
    assert m.ensure("WolffM/tenhands") == dest
    assert len(git.clones) == 2
    assert not (dest / "leftover.txt").exists(), "stale tree must be removed"


# ── reset to a known-clean state ──────────────────────────────────────────


def test_reset_forces_the_tree_to_match_origin(tmp_path):
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[])
    m.reset_to("WolffM/tenhands", "main")
    joined = [" ".join(c) for c in git.calls]
    assert any("fetch origin --prune" in c for c in joined)
    assert any("checkout --force -B main origin/main" in c for c in joined)
    assert any("reset --hard origin/main" in c for c in joined)
    assert any("clean -fdx" in c for c in joined), \
        "gates assume no leftover files from a previous task"


def test_reset_raises_when_a_step_fails(tmp_path):
    git = FakeGit(fail=("reset --hard",))
    m = mgr(tmp_path, git, local_search=[])
    with pytest.raises(CheckoutError, match="reset"):
        m.reset_to("WolffM/tenhands", "main")


def test_reset_clones_first_when_nothing_exists(tmp_path):
    git = FakeGit()
    m = mgr(tmp_path, git, local_search=[])
    m.reset_to("WolffM/brand-new", "main")
    assert len(git.clones) == 1


@pytest.mark.parametrize("value", [
    "WolffM/tenhands",          # a bare slug, as the board stores it
    "wolffm/TENHANDS",          # casing is irrelevant
])
def test_a_bare_slug_normalises_to_itself(value):
    """Regression: this function is handed both full URLs and bare slugs.
    Stripping the first segment unconditionally turned `WolffM/tenhands`
    into `tenhands`, so a slug never matched its own remote and every local
    reference was silently declined."""
    assert _normalise_remote(value) == "wolffm/tenhands"


def test_a_slug_and_its_remote_url_agree():
    assert (_normalise_remote("WolffM/tenhands")
            == _normalise_remote("https://github.com/WolffM/tenhands.git"))


# ── housekeeping: branches and worktrees must not accumulate ──────────────


class PruneGit(FakeGit):
    """Answers `branch --merged` and records deletions."""

    def __init__(self, merged=(), current="main", **kw):
        super().__init__(**kw)
        self.merged, self.current = list(merged), current
        self.deleted = []

    def __call__(self, args, cwd=None, timeout=600):
        self.calls.append(list(args))
        joined = " ".join(args)
        if "branch --merged" in joined:
            return RunResult(True, "\n".join(self.merged) + "\n")
        if "rev-parse --abbrev-ref HEAD" in joined:
            return RunResult(True, self.current + "\n")
        if "branch -D" in joined:
            self.deleted.append(args[-1])
            return RunResult(True, "")
        return super().__call__(args, cwd, timeout)


def pruned(tmp_path, merged, current="main"):
    git = PruneGit(merged=merged, current=current)
    m = mgr(tmp_path, git, local_search=[])
    m.ensure("WolffM/tenhands")
    return m, git, m.prune("WolffM/tenhands")


def test_finished_pipeline_branches_are_deleted(tmp_path):
    """One per landing, forever, and each pins its commits against gc."""
    _, git, removed = pruned(tmp_path, ["taskauto/01aaa", "taskauto/01bbb"])
    assert sorted(removed) == ["taskauto/01aaa", "taskauto/01bbb"]
    assert sorted(git.deleted) == ["taskauto/01aaa", "taskauto/01bbb"]


def test_human_branches_are_never_touched(tmp_path):
    _, git, removed = pruned(tmp_path, ["main", "my-wip", "feature/x",
                                        "taskauto/01aaa"])
    assert removed == ["taskauto/01aaa"]
    assert git.deleted == ["taskauto/01aaa"]


def test_the_base_branch_is_never_deleted(tmp_path):
    _, git, removed = pruned(tmp_path, ["main"])
    assert removed == [] and git.deleted == []


def test_the_checked_out_branch_is_skipped(tmp_path):
    """Deleting the branch HEAD is on fails anyway; it gets collected next
    run once HEAD has moved."""
    _, git, removed = pruned(tmp_path, ["taskauto/01aaa", "taskauto/01bbb"],
                             current="taskauto/01aaa")
    assert removed == ["taskauto/01bbb"]


def test_branches_can_be_explicitly_kept(tmp_path):
    git = PruneGit(merged=["taskauto/01aaa", "taskauto/01bbb"])
    m = mgr(tmp_path, git, local_search=[])
    m.ensure("WolffM/tenhands")
    assert m.prune("WolffM/tenhands", keep=["taskauto/01aaa"]) == ["taskauto/01bbb"]


def test_unmerged_branches_survive(tmp_path):
    """`branch --merged` only lists merged ones — an unmerged branch is the
    last remaining copy of work that did not land."""
    _, git, removed = pruned(tmp_path, [])
    assert removed == []


def test_stale_worktrees_are_pruned(tmp_path):
    """The thing that actually costs disk."""
    _, git, _ = pruned(tmp_path, ["taskauto/01aaa"])
    assert any("worktree prune" in " ".join(c) for c in git.calls)


def test_prune_on_a_missing_clone_is_a_no_op(tmp_path):
    git = PruneGit()
    m = CheckoutManager(root=tmp_path / "nope", local_search=(), run=git)
    assert m.prune("WolffM/tenhands") == []
