"""One-time backfill: write the missing `→ aborted` transition for runs
that aborted before the workflow learned to persist it.

Until issue_workflow.py:_record_abort landed, an aborting workflow only set
its state in memory and returned an IssueResult — nothing on disk recorded
the abort, so `transitions.jsonl` froze at the crash point and the UI
showed the run stuck mid-pipeline (yellow/in-progress) with no explanation.

This script queries the Temporal cluster for each issue's workflow result;
when a workflow COMPLETED with final_state == "aborted" but its on-disk
transition log does not already end in `aborted`, it appends the missing
transition (carrying the real abort_reason) so `current_state` resolves to
`aborted` and the UI colors it red.

Dry-run by default. Pass --apply to actually write.

Usage:
  python3 scripts/backfill_abort_transitions.py                 # dry-run, default batches
  python3 scripts/backfill_abort_transitions.py --apply
  python3 scripts/backfill_abort_transitions.py --apply BATCH_ID [BATCH_ID ...]
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_ROOT = Path(__file__).parent.parent / "state"
DEFAULT_BATCHES = [
    "crimson-kitty-big-batch-2026-05-14",
    "crimson-kitty-big-batch-2026-05-14-msft-v2",
    "crimson-kitty-big-batch-2026-05-14-recover",
]


def _last_transition_state(issue_dir: Path) -> str | None:
    tf = issue_dir / "transitions.jsonl"
    if not tf.exists():
        return None
    state = None
    for line in tf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            state = json.loads(line).get("to", state)
        except ValueError:
            continue
    return state


def _append_transition(issue_dir: Path, from_state: str, reason: str) -> None:
    row = {
        "decided_by": "system:backfill",
        "from": from_state,
        "reason": reason,
        "to": "aborted",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    with (issue_dir / "transitions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


async def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    batches = [a for a in argv[1:] if not a.startswith("--")] or DEFAULT_BATCHES

    from temporalio.client import Client

    client = await Client.connect("localhost:7233", namespace="crimson-kitty")

    planned, skipped = [], 0
    for batch in batches:
        bdir = STATE_ROOT / batch
        if not bdir.is_dir():
            print(f"  (batch dir not found: {batch})")
            continue
        for issue_dir in sorted(p for p in bdir.iterdir() if p.is_dir()):
            issue = issue_dir.name
            last = _last_transition_state(issue_dir)
            if last == "aborted":
                skipped += 1
                continue
            handle = client.get_workflow_handle(f"{batch}-{issue}")
            try:
                desc = await handle.describe()
            except Exception as e:
                print(f"  ? {batch}/{issue}: describe failed ({type(e).__name__})")
                continue
            if desc.status.name != "COMPLETED":
                skipped += 1
                continue
            try:
                res = await handle.result()
            except Exception:
                skipped += 1
                continue
            if not isinstance(res, dict) or res.get("final_state") != "aborted":
                skipped += 1
                continue
            reason = res.get("abort_reason") or "aborted (reason unavailable)"
            planned.append((issue_dir, last or "candidate", reason, batch, issue))

    print(f"\n{'APPLYING' if apply else 'DRY-RUN'} — {len(planned)} backfill(s), "
          f"{skipped} already-correct/skipped\n")
    for issue_dir, from_state, reason, batch, issue in planned:
        print(f"  {batch}/{issue}")
        print(f"    {from_state} -> aborted   {reason[:120]}")
        if apply:
            _append_transition(issue_dir, from_state, reason)

    if planned and not apply:
        print("\nRe-run with --apply to write these transitions.")
    elif apply and planned:
        print(f"\nWrote {len(planned)} aborted transition(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv)))
