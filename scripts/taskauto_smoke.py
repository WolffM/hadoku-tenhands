#!/usr/bin/env python3
"""Smoke-test the hadoku-task board integration against a live board.

Every test so far runs against an injected fake transport, which proves the
client does what I *think* the API does. This proves what the API actually
does — and twice already in this integration the shipped shape differed from
the documented one (agent endpoints need `board`, not just `taskId`; a change
feed exists that the design doc said wouldn't).

Run it through the vault wrapper so HADOKU_TASK_KEY is populated:

    node ../hadoku_site/scripts/secrets/dev-vault.mjs -- \\
        python3 scripts/taskauto_smoke.py <board-handle>

Read-only by default. `--claim <task-id>` additionally exercises the write
path — claim → heartbeat → set-lane → release — and always releases the task
back where it started, including on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from services.task_board import (  # noqa: E402
    TaskBoardClient,
    _ambient_key,
    TaskBoardDomainError,
    TaskBoardError,
    TaskBoardUnavailable,
)
from temporal.taskauto import selection  # noqa: E402

SCHEMA = (Path(__file__).resolve().parents[1] / "docs" / "hadoku-task-automation"
          / "schemas" / "autoland-v1.json")

OK, BAD, INFO = "  ok  ", " FAIL ", "  ..  "


def check(label: str, passed: bool, detail: str = "") -> bool:
    print(f"[{OK if passed else BAD}] {label}" + (f" — {detail}" if detail else ""))
    return passed


def read_only(client: TaskBoardClient, handle: str) -> tuple[bool, object]:
    print(f"\n=== board {handle} ===")
    board = client.get_board(handle)

    ok = True
    ok &= check("board resolves", bool(board.id), f"id={board.id} name={board.name!r}")
    ok &= check(
        "repo is set", bool(board.repo),
        board.repo or "EMPTY — activation payload needs `repo`, or board→checkout "
                      "mapping has nothing to key on")
    ok &= check("automation is active", board.is_automation,
                f"{len(board.lanes)} lane(s), schema={board.schema_id}"
                f" v{board.schema_version}")
    ok &= check("access is writable", board.access in ("owner", "contributor"),
                f"access={board.access!r}"
                + ("" if board.access != "readonly"
                   else " — share must be `contributor`, not `readonly`"))

    if SCHEMA.exists() and board.lanes:
        want = {ln["tag"] for ln in json.loads(SCHEMA.read_text())["lanes"]}
        got = {ln.tag for ln in board.lanes}
        ok &= check("lane set matches autoland-v1", want == got,
                    "" if want == got else
                    f"missing={sorted(want - got)} unexpected={sorted(got - want)}")

    print(f"\n  lanes: " + ", ".join(
        f"{ln.tag}({'agent' if ln.is_agent else 'user'})" for ln in board.lanes))
    print(f"  tasks: {len(board.active_tasks)} active"
          f" / {len(board.tasks)} total")
    for t in board.active_tasks[:10]:
        lane = t.lane(board.lanes) or "(inbox)"
        print(f"    - {t.id}  [{lane}]{' CLAIMED' if t.claimed else ''}  {t.title[:56]}")
    if board.malformed():
        print(f"  MALFORMED (multiple lane tags, need repair): "
              f"{[t.id for t in board.malformed()]}")

    from datetime import datetime, timezone
    decision = selection.choose(board, now=datetime.now(timezone.utc))
    print(f"\n  selection says: {decision}")
    return ok, board


def write_path(client: TaskBoardClient, handle: str, board, task_id: str) -> bool:
    """Exercise claim → heartbeat → set-lane → release, restoring the lane."""
    task = next((t for t in board.active_tasks if t.id == task_id), None)
    if task is None:
        return check("task exists", False, f"{task_id} not on this board")

    origin = task.lane(board.lanes)
    agent_lane = next((ln.tag for ln in board.lanes if ln.is_agent), None)
    if not agent_lane:
        return check("board has an agent lane", False)

    print(f"\n=== write path on {task_id} (from {origin or '(inbox)'}) ===")
    token = None
    ok = True
    try:
        token = client.claim(handle, task_id, lane=agent_lane, lease_seconds=300)
        ok &= check("claim returns a token", bool(token))

        client.heartbeat(handle, task_id, token)
        ok &= check("heartbeat extends the lease", True)

        after = client.get_board(handle)
        moved = next((t for t in after.active_tasks if t.id == task_id), None)
        ok &= check("claim moved the task into the agent lane",
                    moved is not None and moved.lane(after.lanes) == agent_lane,
                    f"lane={moved.lane(after.lanes) if moved else None}")
        ok &= check("board read reports the live claim",
                    moved is not None and moved.claimed)

        try:
            TaskBoardClient(
                base_url=client.base_url, user_key=client.user_key
            ).claim(handle, task_id)
            ok &= check("second claim is refused", False, "it succeeded — the "
                        "lock is not exclusive")
        except TaskBoardDomainError as e:
            ok &= check("second claim is refused", e.code == "CLAIM_HELD",
                        f"code={e.code}")
    finally:
        if token:
            try:
                client.release(handle, task_id, token, lane=origin,
                               outcome="smoke-test")
                print(f"[{OK}] released back to {origin or '(inbox)'}")
            except TaskBoardError as e:
                print(f"[{BAD}] RELEASE FAILED — {task_id} may be stuck in "
                      f"{agent_lane}: {e}")
                ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("handle", help="board handle (ULID) or your own slug")
    ap.add_argument("--claim", metavar="TASK_ID",
                    help="also exercise the write path on this task")
    args = ap.parse_args()

    # Ask the client how it resolves a credential rather than re-checking one
    # source. The env var is only the first of two — falling back to the repo
    # key file is what makes local runs work — and a guard stricter than the
    # thing it guards just refuses runs that would have worked.
    if not _ambient_key():
        print("No board credential: set HADOKU_TASK_KEY or ensure "
              ".devvault.local.json exists.", file=sys.stderr)
        return 2

    client = TaskBoardClient()
    print(f"base_url = {client.base_url}")
    try:
        ok, board = read_only(client, args.handle)
        if args.claim:
            ok &= write_path(client, args.handle, board, args.claim)
    except TaskBoardUnavailable as e:
        sys.stdout.flush()
        print(f"\n[{BAD}] board unreachable: {e}", file=sys.stderr)
        return 2
    except TaskBoardDomainError as e:
        sys.stdout.flush()
        hint = ""
        if e.code == "BOARD_NOT_FOUND":
            hint = ("\n       Either the handle is wrong, or the board isn't shared "
                    "with this key.\n       Note a key that has never been "
                    "registered has no userId, so it\n       cannot be granted "
                    "access at all — and that surfaces here as\n       "
                    "BOARD_NOT_FOUND rather than a permissions error.")
        print(f"\n[{BAD}] {e.code}: {e}{hint}", file=sys.stderr)
        return 1

    print("\n" + ("all checks passed" if ok else "SOME CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
