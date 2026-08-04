"""Fetch a credential the way this repo is meant to: service key → broker.

There are no `.env` files anywhere in the hadoku ecosystem, so a secret a test
needs is not sitting in the environment waiting to be read. It lives in the
vault, and the way in is the per-repo service-tier key in
`.devvault.local.json` plus the env-name → vault-key mapping in
`.devvault.json`. That is exactly the pair `dev-vault.mjs` uses; this is the
Python side of the same contract, so a test can fetch what it needs on its own
instead of the caller having to remember to wrap pytest in the Node wrapper.

**Why this exists rather than "just run the wrapper".** The wrapper is easy to
forget, and forgetting it did not fail — it *skipped*. A test that quietly opts
out when a credential is missing reports the same green as one that ran, so
`test_score_integration_real_cli` sat unrun and nobody could tell from the
output. Making the test fetch its own credential removes the human step that
was silently deciding whether the test happened.

Read-only and never writes: `GET /api/secrets/get/:key` is the whole surface.
The service tier cannot set, lock, list or audit, which is the point of it —
see the vault section of CLAUDE.md.

**Never let a value from here reach an assertion message or a log.** The
functions below return secrets; the diagnostics deliberately report only
whether a fetch succeeded, never what came back.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Optional

#: Same default and override as `dev-vault.mjs`. The broker is reached through
#: edge-router at the gated `/mgmt/*` prefix, never a direct subdomain.
BROKER = os.environ.get("MGMT_API_BASE", "https://hadoku.me/mgmt").rstrip("/")

#: Short on purpose. A test suite must not hang for a minute because the
#: broker is unreachable; failing fast with a clear reason is more useful.
TIMEOUT = 10

#: **Load-bearing, and not obviously so.** `hadoku.me` is behind Cloudflare,
#: whose bot fingerprinting rejects urllib's default `Python-urllib/3.x` agent
#: with HTTP 403 and body `error code: 1010` — before the request ever reaches
#: edge-router or the broker. That is indistinguishable from an ACL denial at
#: the status-code level, so it reads as "this key lacks a grant" and sends you
#: to the operator for a permission that was never the problem. Measured
#: 2026-08-04: identical request, `Python-urllib/3.13` → 403/1010, every other
#: agent tried (`curl/8.5.0`, `node`, this one) → 200. Any honest string works;
#: what must not happen is leaving it unset.
USER_AGENT = "tenhands-tests/1.0 (vault client)"


class VaultUnavailable(RuntimeError):
    """No credential could be resolved, with the reason attached.

    Carries *why* rather than just "missing", because the causes need
    different fixes: no key file (mint one), sealed vault (operator TOTP), no
    ACL grant (`key-acl-sync`), blocked client (User-Agent).
    """


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """The directory holding `.devvault.json` — walked up to, not assumed.

    Tests run from `backend/`, the wrapper runs from the repo root, and CI runs
    from a workspace path that matches neither.
    """
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / ".devvault.json").is_file():
            return parent
    raise VaultUnavailable(
        f"no .devvault.json found above {here} — is this a hadoku checkout?")


@lru_cache(maxsize=1)
def service_key() -> str:
    """The vault-caller key: `HADOKU_VAULT_KEY`, else `.devvault.local.json`.

    Env first so CI can supply it without a file on disk — the file is
    gitignored by design and a fresh checkout never has one.

    **This is not `HADOKU_SERVICE_KEY`.** That one is the *board* credential
    (vault item `KEY_SERVICE_TENHANDS`, identity `tenhands-service-key`) and is
    a different identity with different grants; `services/task_board.py`
    documents at length why the two must never be substituted for each other.
    """
    from_env = os.environ.get("HADOKU_VAULT_KEY", "").strip()
    if from_env:
        return from_env

    path = repo_root() / ".devvault.local.json"
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError:
        raise VaultUnavailable(
            f"no service-tier key: {path} does not exist and HADOKU_VAULT_KEY "
            f"is unset. Operator mints one with `python "
            f"../hadoku_site/scripts/administration.py key-generate --tier "
            f"service --repo ../tenhands`") from None
    except ValueError as e:
        raise VaultUnavailable(f"{path} is not valid JSON: {e}") from None

    key = (raw or {}).get("key")
    if not isinstance(key, str) or not key.strip():
        raise VaultUnavailable(f'{path} must be of the shape {{"key": "<uuid>"}}')
    return key.strip()


@lru_cache(maxsize=1)
def mapping() -> dict:
    """`.devvault.json`'s env-name → vault-key map, minus its `//` comments."""
    path = repo_root() / ".devvault.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise VaultUnavailable(f"could not read {path}: {e}") from None
    return {k: v for k, v in (raw or {}).items()
            if not k.startswith("//") and isinstance(v, str)}


@lru_cache(maxsize=8)
def fetch(env_name: str) -> str:
    """Resolve one credential by the name code reads it under.

    Environment first — if something already exported it (the `dev-vault.mjs`
    wrapper, or a CI job with the secret wired in) that is authoritative and
    there is no reason to spend a network call re-deriving it.
    """
    from_env = os.environ.get(env_name, "").strip()
    if from_env:
        return from_env

    vault_key = mapping().get(env_name)
    if not vault_key:
        raise VaultUnavailable(
            f"{env_name} is not declared in {repo_root() / '.devvault.json'}. "
            f"Add the mapping, then the operator grants it with `key-acl-sync`")

    req = urllib.request.Request(
        f"{BROKER}/api/secrets/get/{urllib.parse.quote(vault_key, safe='')}",
        headers={"X-User-Key": service_key(), "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 404 on this gated prefix is ambiguous by design — edge-router does not
        # advertise a surface to a caller it rejected, so it looks identical to
        # "key not in vault".
        hint = {
            403: "either Cloudflare rejected the client (body `error code: "
                 "1010` — see USER_AGENT above, and check that first, it is "
                 "the cheaper cause) or the key lacks a per-key ACL grant, "
                 "which the operator fixes with `key-acl-sync --repo "
                 "../tenhands`",
            404: "either the key is not in the vault, or edge-router rejected "
                 "this service key (the gated prefix returns 404 for both)",
            503: "the vault is sealed — it seals on almost any deploy and only "
                 "an operator TOTP unlocks it",
        }.get(e.code, "")
        raise VaultUnavailable(
            f"broker returned HTTP {e.code} for {env_name}"
            + (f": {hint}" if hint else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise VaultUnavailable(f"broker at {BROKER} unreachable: {e}") from None
    except ValueError as e:
        raise VaultUnavailable(f"broker returned unparseable JSON: {e}") from None

    value = (body or {}).get("value")
    if not (body or {}).get("success") or not isinstance(value, str) or not value:
        raise VaultUnavailable(
            f"broker response for {env_name} had no usable value")
    return value


def fetch_or_none(env_name: str) -> Optional[str]:
    """`fetch`, but None instead of raising. For callers that have a fallback."""
    try:
        return fetch(env_name)
    except VaultUnavailable:
        return None
