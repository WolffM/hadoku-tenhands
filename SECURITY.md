# Security Posture — TenHands

> Last reviewed: 2026-08 · This document describes the current model. A June 2026
> internal audit found the pre-auth API surface unacceptable; everything below is
> the result of closing it (July 2026).

## Auth model

Every request is gated by a default-deny `before_request` hook
(`_enforce_tier` in `backend/app.py`). TenHands holds no key material of its
own: it resolves the caller's `X-User-Key` against the platform's
`/session/whoami` and admits anything above the public tier. No key → 401;
recognised-but-unprivileged or unknown key → 403.

The only unauthenticated paths are a deliberate four-entry allowlist
(`_PUBLIC_PATHS`): the API-info root, the health endpoint the monitoring probe
hits, and the two `/automation/*` endpoints that publish the lane vocabulary —
public information by design, consumed server-side by the task board with no
credential.

Debug routes (`/api/oss/debug/*`) carry a second, stricter admin gate on top
of the tier gate.

## Secrets

There are no `.env` files. Secrets are fetched at start-up from a vault broker
under a per-repo, per-key ACL; the repo tracks only the *names* of the env vars
it needs (`.devvault.json`). Nothing in this repository — including its full
git history — contains credential values.

## Agent containment

The pipeline dispatches coding agents against forks and sandboxes, never
directly against third-party repositories:

- Fork Actions are disabled at fork time so no workflow fires as a side effect
  of agent pushes.
- Nothing links to an upstream repository until a human explicitly approves
  submission; all agent-facing content is passed through a reference sanitizer
  first (see `docs/crimson-kitty/cross-ref-isolation.md`).
- Agent-authored test commands execute on an isolated sandbox host behind a
  bearer-authenticated, allowlisted runner service — not on the host that
  holds tokens.
- Upstream submission is additionally gated by a per-issue
  `submit_to_upstream` flag; demo batches are forced to `false` server-side.

## CI

The self-hosted runner only executes jobs from same-repo branches; the
fork-facing test job runs on GitHub-hosted runners with no secrets. This repo
does not use `pull_request_target`.

## Reporting

If you find a vulnerability, please open a GitHub security advisory on this
repository (Security → Report a vulnerability) rather than a public issue.
