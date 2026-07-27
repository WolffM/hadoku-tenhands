# `AGGREGATOR_SCRAPER_API_KEY` has been removed — drop the manifest line

**Date:** 2026-07-27 · **Filed by:** hadoku_site (platform)

## What changed

The vault item `AGGREGATOR_SCRAPER_API_KEY` has been **deleted**, along with the
other purpose-scoped scraper keys `OSS_SCRAPER_KEY` and `JOBPLATFORM_SCRAPER_KEY`.

Your `.devvault.json` still declares it, so `dev-vault.mjs` will report it as
missing. **No code in this repo reads the env var it maps to** — a
gitignore-blind search found zero consumers — so this is a stale declaration, not
a broken dependency.

## Why

Per-pair keys for app-to-app calls are not the model. Inter-app communication is
authorised by **service tier**: each app presents its own service identity, and
any service-tier key is accepted. There is no need for a separate credential per
(caller, callee) pair.

The cutover already happened on 2026-05-29 ("Part C") — the CF worker bindings
were repointed to each app's primary key (`AGGREGATOR_SERVICE_KEY`,
`JOBPLATFORM_SERVICE_KEY`), and the adhoc keys were left in the vault pending a
grace-period prune that never ran. This is that prune, overdue by two months.

Both primary keys are verified working against the scraper today
(`GET scraper.hadoku.me/api/v1/oss-recon/status` → 200).

## What to do

Remove the `AGGREGATOR_SCRAPER_API_KEY` line from `.devvault.json`, then re-run
`node ../hadoku_site/scripts/secrets/dev-vault.mjs --check`.

If you later need to call the scraper from this repo, use this app's own
service-tier key — do not mint a purpose-scoped one.
