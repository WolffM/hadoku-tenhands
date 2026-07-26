# Vault key request — `tenhands-taskauto`

**To:** hadoku_site vault operators
**From:** tenhands / hadoku-task-automation
**Date:** 2026-07-25
**Status:** blocking — the service is `stopped` in pm2 until this is granted

---

## The ask, in one block

Please mint a service-tier vault key, install it at the path below, and grant it
exactly three secrets:

```
file    hadoku_site/services/pm2/taskauto.vaultkey
mode    0600, owner hadoku          (gitignored — .gitignore:105 services/pm2/*.vaultkey)
tier    service
grants  TENHANDS_SERVICE_KEY
        CLAUDE_CODE_OAUTH_TOKEN
        HADOKU_SITE_TOKEN
```

Three grants, no more. The wrapper declares four *env names* but only three
distinct vault keys — `GH_TOKEN` and `HADOKU_SITE_TOKEN` both resolve
`HADOKU_SITE_TOKEN`.

**Filename warning.** It must be `taskauto.vaultkey`, **not**
`tenhands-taskauto.vaultkey`. `vault-fetch.mjs` derives the name from the
*wrapper* filename minus `-wrapper.mjs` (`taskauto-wrapper.mjs` → `taskauto`),
which is not the pm2 service name. This is exactly the mistake that produced the
incident below.

## Why — what is broken right now

`tenhands-taskauto` was reloaded onto the host and crashlooped, 2 restarts,
then was deliberately stopped so it would not flap:

```
Error: fetch TENHANDS_SERVICE_KEY failed: HTTP 403 access denied
    at fetchSecret (services/pm2/lib/vault-fetch.mjs:212:9)
    at async file:///…/services/pm2/taskauto-wrapper.mjs:23:1
```

That 403 is misleading. The boot banner is the real evidence:

```
[vault-fetch] wrapper=taskauto … key=(empty) source=(none — relies on loopback bypass)
```

The wrapper sent **no `X-User-Key` at all**, because no keyfile exists at the
path it looks for. The loopback bypass does not cover ACL-gated secrets, so the
first gated fetch 403s. The failure is a *missing credential* presenting as a
*missing grant*.

Blast radius was contained: `tenhands` and `tenhands-temporal` stayed online
throughout, because this service has its own wrapper.

## Why no existing key can be reused

Three candidates, all rejected:

| candidate | grants | verdict |
|---|---|---|
| `0470497b…` — `tenhands/.devvault.local.json` | 5 | **Missing `TENHANDS_SERVICE_KEY`.** Its ACL is synced from this repo's `.devvault.json`, which does not declare it. Also a *developer* credential; using it as a production service identity conflates the two. |
| `dfe98523…` — `services/pm2/tenhands.vaultkey` | 16 | Has all three, so symlinking it would start the service in one command — and that is precisely why it should not be done. See below. |
| loopback bypass (no key) | n/a | What it does today. Does not cover ACL-gated secrets. |

**On reusing the tenhands wrapper key.** It carries 16 grants including
`TENHANDS_ADMIN_KEY`, `TENHANDS_MSFT_SSO` and both Discord webhooks. This
service supervises an autonomous coding agent that merges to `main` without
human review, and its containment story is still open (README §4.3: the agent
runs headless on the prod host with a scrubbed environment but no filesystem or
network confinement). Handing that supervisor an identity with five times the
reach it declares is the wrong direction. Three grants is not pedantry here —
it is the only part of the privilege story currently under our control.

## Open question for you

`HADOKU_TASK_KEY` is currently mapped to `TENHANDS_SERVICE_KEY` — we reuse the
edge service-tier monitoring key (key name `tenhands-monitoring`) as the
hadoku-task board credential rather than minting a board-specific secret. That
was a deliberate "no new secret needed" call, but it does mean one credential
spans two unrelated systems. **If you would rather this pipeline hold its own
board credential, say so and we will declare a separate key instead** — it is a
one-line change to `taskauto-wrapper.mjs` plus a new secret.

## Ordering constraint

Please **grant before we declare**. `dev-vault.mjs` refuses *every* command if a
repo's `.devvault.json` declares an entry the key is not granted, so adding the
`HADOKU_TASK_KEY` line ahead of the grant would break all local tooling for this
repo, not just the new path. The declaration is currently held back on purpose —
see the `//hadoku-task` comment in `.devvault.json`.

## Verification, once granted

```sh
# 1. the key resolves exactly the three secrets and nothing else
curl -s -H "X-User-Key: $(cat services/pm2/taskauto.vaultkey)" \
     http://localhost:4000/api/secrets/acl/me

# 2. the service boots with a real key — banner must NOT say key=(empty)
pm2 start tenhands-taskauto && pm2 logs tenhands-taskauto --lines 20 --nostream
```

Expected banner: `wrapper=taskauto … key=<8 chars>… source=…/taskauto.vaultkey`.

Note the service still defaults to `TASKAUTO_LIVE=0` — it runs the full pipeline
and stops before pushing. Arming it is a separate, deliberate act.

## Second, unrelated finding — `promptsmith`

Found while auditing every wrapper for this same gap. `promptsmith-wrapper.mjs`
declares 3 secrets and has **no `promptsmith.vaultkey`**. It is `online` with 0
restarts only because it has not restarted since ACL enforcement; it will fail
the same way whenever it next does. Every other key-declaring wrapper
(`archive-bot`, `conjure`, `cron-worker`, `pygmalion`, `scraper`, `tenhands`,
`watchparty`) has its keyfile. Not ours to fix, but you should know.

## Already done on our side

hadoku_site `4ec59804` — `vault-fetch.mjs` now warns at boot when a wrapper
declares secrets but carries no key, naming the exact path it expected, and
annotates the 403 with which of the two problems it actually is. Deliberately a
warning and not a throw: wrappers with `vaultKeys: {}` legitimately run keyless,
and throwing in shared code would take out every service at once.
