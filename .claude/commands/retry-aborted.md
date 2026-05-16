Re-dispatch the CRASHED runs of a crimson-kitty batch — runs killed by an
activity failure (fork 403, timeout, …), not by a gate decision.

Crashed runs have no gate verdict and are worth retrying. Gate-fail and
operator aborts are decisions that re-dispatch won't change, so they are
skipped.

Usage:
- `/retry-aborted crimson-kitty-big-batch-2026-05-14`        → dry-run
- `/retry-aborted crimson-kitty-big-batch-2026-05-14 --apply` → actually dispatch

Run this command, substituting the batch id the user passed:

```bash
python3 /mnt/c/Users/Hadoku/Documents/repos/vibedispatch/scripts/retry_aborted.py $BATCH_ID $EXTRA_FLAGS
```

The script is dry-run by default — it lists what would be retried vs
skipped. Only with `--apply` does it POST to `/api/temporal/dispatch`,
starting a fresh batch `<batch>-retry-<timestamp>` with the crashed issues.

Always show the dry-run output and let the user confirm before re-running
with `--apply`, unless they already passed `--apply` themselves.
