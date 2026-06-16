Show the current crimson-kitty operator inbox — every workflow deferred and
awaiting an approve / abort / retry decision.

Run this command and present the output as a clean status report:

```bash
python3 scripts/temporal_snapshot.py inbox
```

The script fetches the tenhands admin key from the vault broker and
calls the production dispatch API (`/dispatch/api/temporal/inbox`). Each
entry shows the issue, gate, judge score, batch, reason, and workflow id.

If it fails because the vault broker returns an error, mgmt-api is likely
down (the better-sqlite3 platform clobber) — say so directly and point at
the Windows-side `pnpm rebuild better-sqlite3` + `pm2 restart mgmt-api` fix.
