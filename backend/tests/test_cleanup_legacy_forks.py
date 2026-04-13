"""Unit tests for scripts/cleanup_legacy_forks.py.

The script's only side effect surface is `_run_gh()`. Tests monkeypatch that
function with a fake gh runner that responds to argv patterns with canned
output, then assert on what the script asks gh to do.
"""

import json
import os
import sys

import pytest

# Make scripts/ importable.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SCRIPTS_DIR = os.path.join(_REPO_ROOT, "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import cleanup_legacy_forks as clf  # noqa: E402


# ── Fake gh runner ────────────────────────────────────────────────────────────


class FakeGh:
    """Records every gh invocation and replays canned responses by pattern."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.fail_on: set[str] = set()

    def __call__(self, args: list[str]) -> str:
        self.calls.append(list(args))
        joined = " ".join(args)

        for needle in self.fail_on:
            if needle in joined:
                raise clf.GhError(f"forced failure on {needle}")

        if args[0] == "api" and "users/" in args[1] and "/repos" in args[1]:
            return json.dumps([
                {"name": "markitdown", "full_name": "WolffM/markitdown"},
                {"name": "mermaid", "full_name": "WolffM/mermaid"},
            ])

        if args[0] == "api" and args[1] == "repos/WolffM/markitdown":
            return json.dumps({
                "full_name": "WolffM/markitdown",
                "name": "markitdown",
                "parent_full": "microsoft/markitdown",
                "default_branch": "main",
                "pushed_at": "2026-03-11T12:00:00Z",
                "archived": False,
            })

        if args[0] == "api" and args[1] == "repos/WolffM/mermaid":
            return json.dumps({
                "full_name": "WolffM/mermaid",
                "name": "mermaid",
                "parent_full": "mermaid-js/mermaid",
                "default_branch": "develop",
                "pushed_at": "2026-03-12T08:30:00Z",
                "archived": False,
            })

        if args[0] == "api" and "/branches" in args[1]:
            return json.dumps([
                {"name": "main", "sha": "aaa111"},
                {"name": "fix-issue-9", "sha": "bbb222"},
            ])

        if args[0] == "api" and "/commits/" in args[1]:
            return json.dumps({
                "sha": "deadbeef",
                "message": "last commit",
                "date": "2026-03-12T08:30:00Z",
            })

        if args[:2] == ["pr", "list"]:
            if "WolffM/markitdown" in args:
                return json.dumps([
                    {
                        "number": 9,
                        "title": "Fix blank cells",
                        "headRefName": "fix-issue-9",
                        "baseRefName": "main",
                        "url": "https://github.com/WolffM/markitdown/pull/9",
                        "isCrossRepository": False,
                    }
                ])
            return json.dumps([])

        if args[:2] == ["repo", "delete"]:
            return ""

        raise AssertionError(f"unexpected gh call: {args}")


@pytest.fixture
def fake_gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(clf, "_run_gh", fake)
    return fake


# ── list_forks ────────────────────────────────────────────────────────────────


def test_list_forks_returns_parsed_records(fake_gh):
    forks = clf.list_forks("WolffM")
    assert len(forks) == 2
    assert forks[0]["nameWithOwner"] == "WolffM/markitdown"
    assert forks[0]["parent"]["nameWithOwner"] == "microsoft/markitdown"
    assert forks[0]["defaultBranchRef"]["name"] == "main"
    # Used the REST endpoint, not the GraphQL `repo list` (which trips SAML).
    list_calls = [c for c in fake_gh.calls if c[0] == "api" and "users/" in c[1]]
    assert len(list_calls) == 1
    assert "type=owner" in list_calls[0][1]
    # And then enriched each fork with a per-repo GET.
    enrich_calls = [
        c for c in fake_gh.calls
        if c[0] == "api" and c[1].startswith("repos/WolffM/")
        and "/branches" not in c[1] and "/commits/" not in c[1]
    ]
    assert sorted(c[1] for c in enrich_calls) == [
        "repos/WolffM/markitdown",
        "repos/WolffM/mermaid",
    ]


def test_list_forks_raises_on_gh_error(fake_gh):
    fake_gh.fail_on.add("users/WolffM/repos")
    with pytest.raises(clf.GhError):
        clf.list_forks("WolffM")


def test_list_forks_continues_when_enrichment_fails(fake_gh):
    """Per-fork enrich failures must not abort the whole listing."""
    fake_gh.fail_on.add("repos/WolffM/mermaid")
    forks = clf.list_forks("WolffM")
    assert len(forks) == 2
    # mermaid kept its name even though enrichment failed
    mermaid = next(f for f in forks if f["name"] == "mermaid")
    assert mermaid["nameWithOwner"] == "WolffM/mermaid"
    assert mermaid["parent"] is None


# ── gather_metadata ───────────────────────────────────────────────────────────


def test_gather_metadata_collects_branches_commit_and_open_prs(fake_gh):
    forks = clf.list_forks("WolffM")
    record = clf.gather_metadata(forks[0])

    assert record["nameWithOwner"] == "WolffM/markitdown"
    assert record["parent"] == "microsoft/markitdown"
    assert record["default_branch"] == "main"
    assert record["pushed_at"] == "2026-03-11T12:00:00Z"
    assert record["archived"] is False
    assert record["branches"] == [
        {"name": "main", "sha": "aaa111"},
        {"name": "fix-issue-9", "sha": "bbb222"},
    ]
    assert record["last_commit"]["sha"] == "deadbeef"
    assert len(record["open_pr_refs"]) == 1
    assert record["open_pr_refs"][0]["number"] == 9
    assert record["errors"] == []


def test_gather_metadata_records_errors_without_raising(fake_gh):
    fake_gh.fail_on.add("/branches")
    forks = clf.list_forks("WolffM")
    record = clf.gather_metadata(forks[0])

    assert record["branches"] == []
    assert any("branches" in e for e in record["errors"])
    # other fields still populated
    assert record["last_commit"]["sha"] == "deadbeef"


# ── write_backup ──────────────────────────────────────────────────────────────


def test_write_backup_writes_one_record_per_line(tmp_path):
    records = [
        {"nameWithOwner": "WolffM/a", "x": 1},
        {"nameWithOwner": "WolffM/b", "x": 2},
    ]
    backup = tmp_path / "nested" / "backup.jsonl"
    clf.write_backup(records, backup)

    assert backup.exists()
    lines = backup.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["nameWithOwner"] == "WolffM/a"
    assert parsed[1]["nameWithOwner"] == "WolffM/b"


# ── main: dry-run vs confirm ──────────────────────────────────────────────────


def test_main_dry_run_writes_backup_and_does_not_delete(fake_gh, tmp_path):
    backup = tmp_path / "backup.jsonl"
    rc = clf.main([
        "--owner", "WolffM",
        "--backup", str(backup),
    ])
    assert rc == 0
    assert backup.exists()
    lines = backup.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # Crucially: no `repo delete` calls were issued.
    delete_calls = [c for c in fake_gh.calls if c[:2] == ["repo", "delete"]]
    assert delete_calls == []


def test_main_confirm_deletes_every_fork_including_those_with_open_prs(
    fake_gh, tmp_path
):
    backup = tmp_path / "backup.jsonl"
    rc = clf.main([
        "--owner", "WolffM",
        "--backup", str(backup),
        "--confirm",
    ])
    assert rc == 0

    # Both forks deleted — including WolffM/markitdown which had an open PR.
    deleted = [c[2] for c in fake_gh.calls if c[:2] == ["repo", "delete"]]
    assert sorted(deleted) == ["WolffM/markitdown", "WolffM/mermaid"]

    # Backup still recorded the open PR for the deleted fork.
    records = [json.loads(line) for line in backup.read_text().splitlines()]
    markitdown = next(r for r in records if r["nameWithOwner"] == "WolffM/markitdown")
    assert len(markitdown["open_pr_refs"]) == 1


def test_main_confirm_returns_nonzero_when_a_delete_fails(fake_gh, tmp_path):
    fake_gh.fail_on.add("repo delete WolffM/mermaid")
    backup = tmp_path / "backup.jsonl"
    rc = clf.main([
        "--owner", "WolffM",
        "--backup", str(backup),
        "--confirm",
    ])
    assert rc == 1


def test_main_dry_run_and_confirm_are_mutually_exclusive(fake_gh, tmp_path):
    with pytest.raises(SystemExit):
        clf.main([
            "--dry-run", "--confirm",
            "--backup", str(tmp_path / "b.jsonl"),
        ])
