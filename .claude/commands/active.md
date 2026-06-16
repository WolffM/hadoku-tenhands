Show the current state of all ACTIVE crimson-kitty batches — batches that
still have deferred work — with each batch's run-state breakdown and the
specific runs parked in the inbox.

Run this command and present the output as a clean status report:

```bash
python3 scripts/temporal_snapshot.py active
```

The script fetches the tenhands admin key from the vault broker and
calls the production dispatch API (`/dispatch/api/temporal/batches` plus
per-batch detail). Archived batches (no deferred work) are counted but not
expanded.

If it fails because the vault broker returns an error, mgmt-api is likely
down (the better-sqlite3 platform clobber) — say so directly and point at
the Windows-side `pnpm rebuild better-sqlite3` + `pm2 restart mgmt-api` fix.
