"""hadoku-task board client — the TaskSource for hadoku-task-automation.

Thin, typed wrapper over `https://hadoku.me/task/api`. The board is where a
human files work and watches it move; the claim protocol is the lock that
keeps two runners off one task. See docs/hadoku-task-automation/README.md.

**Why this does not follow `_call_aggregator`'s shape.** That helper returns
`None` on every failure, which is right for a display read — a missing CVS
score degrades to "no score". It is wrong here. A claim protocol has to
distinguish "another runner holds this" (move on, normal) from "your lease
was taken" (abort, write NOTHING) from "the network blipped" (retry later).
Collapsing those into `None` would make the runner silently do the wrong
thing in two of the three cases, so every failure here raises something
specific.

The split that matters to callers:

  TaskBoardDomainError  the board said no, and meant it. Deterministic —
                        retrying the identical request gets the same answer.
  TaskBoardUnavailable  we never got a verdict (timeout, connection, 5xx).
                        Retrying later is reasonable; the request may or may
                        not have been applied, so treat writes as unknown.

Transport is injected (`transport=`) so tests exercise the full
request/response mapping without a network or a live board.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = "https://hadoku.me/task/api"

# Server-side lease policy (worker/src/routes/board-claims.ts). Mirrored here
# only so callers can reason about heartbeat cadence — the server clamps
# regardless of what we ask for, and it assigns the expiry itself, so a
# runner's clock can never extend a lease.
DEFAULT_LEASE_SECONDS = 1800  # 30 min
MAX_LEASE_SECONDS = 3600  # 1 h

# In-run retry for reads only — see the comment in `_call`. Kept small: another
# sweep is always coming, so riding out a long outage is the backstop cron's
# job, not this loop's. Three attempts with a 1s/2s backoff covers the
# single-blip case (which is what `GET /boards → 502` was on 2026-08-10) and
# adds at most ~3s to a run that was going to die anyway.
_GET_ATTEMPTS = 3
_GET_BACKOFF_S = 1.0


# ── Errors ────────────────────────────────────────────────────────────────


class TaskBoardError(Exception):
    """Base for every failure this client raises."""


class TaskBoardUnavailable(TaskBoardError):
    """No verdict from the board: timeout, connection failure, or 5xx.

    A write that raises this has an UNKNOWN outcome — it may have been
    applied. Re-read the board before assuming it wasn't.
    """


class TaskBoardDomainError(TaskBoardError):
    """The board returned a structured refusal.

    `code` is the machine-readable string from the response body; retrying
    the same request unchanged will get the same answer.
    """

    code: str = ""

    def __init__(self, message: str, *, code: str = "", status: int = 0,
                 body: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code or self.code
        self.status = status
        self.body = body or {}


class ClaimHeld(TaskBoardDomainError):
    """409 — a live lease holds this task. Move on to the next one.

    Normal and expected whenever more than one runner polls a board; it is
    not an error condition. `holder` / `expires_at` come from the body.
    """

    code = "CLAIM_HELD"

    @property
    def holder(self) -> str:
        return self.body.get("holder", "")

    @property
    def expires_at(self) -> str:
        return self.body.get("expiresAt", "")


class LeaseLost(TaskBoardDomainError):
    """409 — our token no longer holds the claim.

    **Abort and write nothing.** Either the lease expired and another runner
    took it, or the board owner force-dropped it via `POST /agent/cancel`,
    which is how a human cancels in-flight work. Both mean the same thing to
    us: someone else owns this task now, and anything we write would be
    trampling them.
    """

    code = "LEASE_LOST"


class LaneUnknown(TaskBoardDomainError):
    """422 — the destination lane isn't on this board.

    Usually a re-activation removed it mid-flight. Abort cleanly rather than
    writing into a phantom lane.
    """

    code = "LANE_UNKNOWN"


class LaneNotEditable(TaskBoardDomainError):
    """403 — wrote an `agent` lane through a path that doesn't hold a claim."""

    code = "LANE_NOT_EDITABLE"


class LaneInvalid(TaskBoardDomainError):
    """422 — the task carries zero or two lane tags. Repair it, don't retry."""

    code = "LANE_INVALID"


class LaneChanged(TaskBoardDomainError):
    """409 — the optional `ifCurrentLane` guard didn't match.

    A human retagged the task mid-claim. The release wrote nothing.
    """

    code = "LANE_CHANGED"


class NotesChanged(TaskBoardDomainError):
    """409 — the optional `ifNotesHash` guard didn't match.

    A human edited the plan mid-claim. The release wrote nothing, and — unlike
    `LeaseLost` — **our claim is still live**, so the caller must hand it back
    rather than walk away and leave the task pinned until the lease expires.

    `current_notes_hash` is the digest of what the board holds now, so a caller
    can re-plan against it without a second read.
    """

    code = "NOTES_CHANGED"

    @property
    def current_notes_hash(self) -> str:
        return self.body.get("currentNotesHash", "")


class StatusInvalid(TaskBoardDomainError):
    """422 — the `status` payload isn't the documented shape.

    An unknown `kind`, a missing or oversized `label`, or an `href` that isn't
    http(s). Deterministic: fix the payload, don't retry it.
    """

    code = "STATUS_INVALID"


class TaskNotFound(TaskBoardDomainError):
    """404 — deleted mid-job. Treat as handled; there's nothing to release."""

    code = "TASK_NOT_FOUND"


class BoardNotFound(TaskBoardDomainError):
    """404 — bad handle, or the board isn't shared with our key."""

    code = "BOARD_NOT_FOUND"


class VersionConflict(TaskBoardDomainError):
    """409 — our cached version is stale. Re-pull and retry."""

    code = "VERSION_CONFLICT"


class NotesTooLarge(TaskBoardDomainError):
    """413 — notes exceeded 64 KiB. Truncate or link out; don't retry as-is."""

    code = "NOTES_TOO_LARGE"


class Forbidden(TaskBoardDomainError):
    """403 — our key lacks the access this call needs.

    Most likely: readonly on a board we need to write, or attempting an
    owner-only call. We are a `contributor` and never call owner-only
    endpoints, so in practice this means the share is wrong.
    """

    code = "FORBIDDEN"


class RateLimited(TaskBoardDomainError):
    """429 — backing off is mandatory, not optional.

    The board auto-blacklists after 3 violations, so a tight retry loop is
    actively dangerous: it converts a slow poll into a locked-out key.
    Honour `retry_after`.
    """

    code = "RATE_LIMITED"

    @property
    def retry_after(self) -> int:
        try:
            return int(self.body.get("retryAfter") or 60)
        except (TypeError, ValueError):
            return 60


class NameNotFound(TaskBoardDomainError):
    """404 — no registered key carries that display name.

    Note the status: 404, not 409. Shares are granted by display name, and
    an unregistered name is a missing thing rather than a conflicting one.
    """

    code = "NAME_NOT_FOUND"


class NoUserId(TaskBoardDomainError):
    """409 — the grantee key exists but has never signed in, so it has no id.

    Fixed by calling `POST /session/create` once with that key; it lazily
    mints the userId that sharing resolves against.
    """

    code = "NO_USER_ID"


class BoardSchemaLocked(TaskBoardDomainError):
    """409 — tag mutation attempted on a locked automation board."""

    code = "BOARD_SCHEMA_LOCKED"


class DigestMismatch(TaskBoardDomainError):
    """409 — the activation digest is stale; re-run the dry run.

    Carries `currentDigest`, so a caller can retry without a second preview.
    """

    code = "DIGEST_MISMATCH"

    @property
    def current_digest(self) -> str:
        return self.body.get("currentDigest", "")


class LaneSetInvalid(TaskBoardDomainError):
    """422 — the activation payload's lane set is structurally invalid."""

    code = "LANE_SET_INVALID"


class BadRequest(TaskBoardDomainError):
    """400 — malformed request. Deterministic; never worth retrying."""

    code = "BAD_REQUEST"


_ERRORS_BY_CODE: dict[str, type[TaskBoardDomainError]] = {
    cls.code: cls
    for cls in (
        ClaimHeld, LeaseLost, LaneUnknown, LaneNotEditable, LaneInvalid,
        LaneChanged, NotesChanged, StatusInvalid,
        TaskNotFound, BoardNotFound, VersionConflict,
        NotesTooLarge, Forbidden, RateLimited,
        NameNotFound, NoUserId, BoardSchemaLocked, DigestMismatch,
        LaneSetInvalid, BadRequest,
    )
}

#: Every code the board can emit, mirrored from its OpenAPI document.
#: hadoku-task's `openapi-verify` harness fails their build in both
#: directions — a code they emit that isn't enumerated, or an enumerated
#: value nothing emits — so this list is theirs to grow, not ours to guess.
KNOWN_CODES = frozenset(_ERRORS_BY_CODE)

#: Release wrote nothing. LEASE_LOST means someone else owns the task;
#: LANE_CHANGED means a human retagged it mid-claim; NOTES_CHANGED means a
#: human edited the plan mid-claim. Different causes, identical consequence for
#: the write: abort, write nothing.
#:
#: They differ in one way the caller must not collapse — **whether we still
#: hold the claim**. Only LEASE_LOST means we don't. The other two leave a live
#: token that nothing will release unless the caller hands it back, and an
#: orphaned claim idles the whole repo lane until the lease expires.
RELEASE_ABORTED = (LeaseLost, LaneChanged, NotesChanged)

#: Release aborted but our token is STILL LIVE, so the claim has to be handed
#: back explicitly. `LeaseLost` is deliberately absent: there is no claim left
#: to give up, and a release would fail too.
RELEASE_ABORTED_CLAIM_HELD = (LaneChanged, NotesChanged)


# ── Board shapes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Lane:
    tag: str
    label: str
    order: int
    editable_by: str  # "user" | "agent"
    #: `owner/name` for a v3 repo lane, empty otherwise.
    #:
    #: Carried as an unknown key on the lane object in the activation payload.
    #: `validateLaneSet` preserves what it doesn't interpret ("we validate the
    #: four we interpret and keep the rest"), so this round-trips without
    #: hadoku-task knowing it exists — which is why multi-repo needed no server
    #: change. `boards.repo` remains the single-repo fallback.
    repo: str = ""

    @property
    def is_agent(self) -> bool:
        return self.editable_by == "agent"

    @property
    def is_repo_lane(self) -> bool:
        return bool(self.repo)


#: The chip's closed vocabulary, mirroring `TASK_STATUS_KINDS` in hadoku-task's
#: `src/domain/types.ts`. Four states, because four is what a human tells apart
#: at a glance: it's moving / it wants me / it's stuck / it's finished.
#:
#: **Hardcoded on both sides, deliberately.** We asked them to serve this
#: alongside the lane contracts so it couldn't drift, the way lane names can't;
#: they declined, and they were right — "a `kind` nobody has a stylesheet rule
#: for renders no better for having been downloaded". The vocabulary is code at
#: both ends. What keeps it honest is that a value they don't know is a hard
#: `422 STATUS_INVALID` at the boundary, not a blank chip nobody can explain.
TASK_STATUS_KINDS = ("working", "waiting", "blocked", "done")

#: Longest `label` the chip will carry — a phrase on a card, not a log line.
MAX_STATUS_LABEL_LENGTH = 120


@dataclass(frozen=True)
class TaskStatus:
    """What the pipeline is doing to a task, as the board renders it.

    `label` is ours and is never parsed by anyone; `kind` is the closed set the
    UI styles; `href` makes the chip a link, and is restricted to http(s)
    because it lands in an `<a href>`.

    Validated here as well as at the far end so a typo fails in our own tests
    rather than as a 422 in production — the same reason `validate_lane_set`
    exists on this side.
    """

    kind: str
    label: str
    href: str = ""

    def __post_init__(self) -> None:
        if self.kind not in TASK_STATUS_KINDS:
            raise ValueError(
                f"status kind {self.kind!r} is not one of "
                f"{', '.join(TASK_STATUS_KINDS)}")
        if not self.label or not self.label.strip():
            raise ValueError("status needs a non-empty label")
        if len(self.label) > MAX_STATUS_LABEL_LENGTH:
            raise ValueError(
                f"status label is {len(self.label)} chars, "
                f"over the {MAX_STATUS_LABEL_LENGTH} cap")
        if self.href and not self.href.startswith(("http://", "https://")):
            raise ValueError(f"status href {self.href!r} is not http(s)")

    def to_payload(self) -> dict:
        body = {"kind": self.kind, "label": self.label}
        if self.href:
            body["href"] = self.href
        return body


def _status_from(d: Any) -> Optional[TaskStatus]:
    """Read a status off a board payload, tolerating anything unusable.

    A read must not fail because the far end grew a `kind` we don't know yet —
    that is precisely the case where the rest of the board is still worth
    having. Writes stay strict; reads degrade to `None`.
    """
    if not isinstance(d, dict):
        return None
    try:
        return TaskStatus(kind=d.get("kind", ""), label=d.get("label", ""),
                          href=d.get("href") or "")
    except ValueError:
        logger.warning("ignoring unreadable task status: %r", d)
        return None


def notes_hash(notes: Optional[str]) -> str:
    """The `ifNotesHash` digest: hex SHA-256 of the notes as UTF-8.

    Absent notes hash as the EMPTY STRING, not as an absent hash — that
    convention is what lets a caller guard "this task had no plan when I
    claimed it" without a nullable digest.

    No trimming, no newline normalisation, no canonicalisation: the bytes as
    stored are the bytes hashed. Anything else would be a second format both
    repos have to agree on and drift apart over. Defined in
    `src/domain/utils/notesHash.ts` on their side, which states this same rule
    and gives this exact Python line as the equivalent.
    """
    return hashlib.sha256((notes or "").encode("utf-8")).hexdigest()


#: Hex SHA-256 of the empty string — what absent notes hash to.
EMPTY_NOTES_HASH = notes_hash("")


@dataclass(frozen=True)
class BoardTask:
    id: str
    title: str
    notes: str
    tag: str  # space-separated tag string; the lane is a token within it
    metadata: dict
    claimed: bool
    #: The agent's chip, or None when nothing has reported one. Read-tolerant:
    #: an unreadable payload degrades to None rather than failing the board.
    status: Optional[TaskStatus] = None
    # 'Active' | 'Completed' | 'Deleted'. Archived tasks still come back in the
    # board read, so anything that picks up work must filter on this — see
    # `BoardSnapshot.active_tasks`.
    state: str = "Active"
    created_at: str = ""
    updated_at: str = ""
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.state == "Active"

    @property
    def last_touched(self) -> str:
        """When the human last changed this task, as an ISO 8601 string.

        `updatedAt` is only set on edit, so a freshly captured task has none —
        fall back to `createdAt`. ISO 8601 UTC strings compare correctly
        lexicographically, which is all the settle-delay check needs.
        """
        return self.updated_at or self.created_at

    def lane_tags(self, lanes: list[Lane]) -> list[str]:
        """Every lane tag this task carries — normally zero or one.

        Tags are one space-separated string, not an array, so "has no lane"
        and "has no tags" are different questions and conflating them would
        strand a task.

        This used to add "a user is free to add their own (`urgent`,
        `someday`) alongside a lane tag". **That is true of a standard board
        and false of an automation board**, which is the only kind we drive:
        `assertHumanLaneWrite` rejects any tag containing whitespace, and
        `agentLaneTag` normalises the agent path to a single token. One tag,
        and it must be a lane.

        That constraint is why autoland v3 puts *repos* on the tag axis and
        moves pipeline state to `status` — there was never a second tag
        available to hold both.
        """
        known = {ln.tag for ln in lanes}
        return [t for t in self.tag.split() if t in known]

    def lane(self, lanes: list[Lane]) -> Optional[str]:
        """The task's lane, or None if it has zero or several.

        A task carrying two lane tags is malformed — the board raises
        LANE_INVALID on write — so we surface None rather than silently
        picking one. Use `lane_tags()` to tell the two None cases apart.
        """
        found = self.lane_tags(lanes)
        return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class BoardSnapshot:
    id: str
    name: str
    handle: str
    repo: str
    mode: str
    lanes: list[Lane]
    tasks: list[BoardTask]
    schema_id: str
    schema_version: int
    access: str
    version: int

    @property
    def is_automation(self) -> bool:
        return bool(self.lanes)

    @property
    def repo_lanes(self) -> list[Lane]:
        """The v3 lanes — one per repo, in declared order.

        Empty on a v1/v2 board, whose lanes are pipeline states and carry no
        `repo`. That emptiness is the version check: anything driving repo
        lanes finds nothing to do rather than misreading `planning` as a repo.
        """
        return sorted((ln for ln in self.lanes if ln.is_repo_lane),
                      key=lambda ln: ln.order)

    def repo_for(self, lane_tag: str) -> str:
        for ln in self.lanes:
            if ln.tag == lane_tag:
                return ln.repo
        return ""

    @property
    def active_tasks(self) -> list[BoardTask]:
        """Tasks that still exist as work.

        Completed and Deleted tasks are archived, not removed, so they come
        back in the board read. Everything that selects work must start here.
        """
        return [t for t in self.tasks if t.is_active]

    def tasks_in(self, lane_tag: str) -> list[BoardTask]:
        return [t for t in self.active_tasks if t.lane(self.lanes) == lane_tag]

    def untagged(self) -> list[BoardTask]:
        """Inbox tasks — capture that hasn't entered a lane yet.

        "No LANE tag", not "no tags". A task the human labelled `urgent`
        is still raw Inbox capture; treating it as tagged would make it
        invisible to every branch of selection and strand it silently.
        """
        return [t for t in self.active_tasks if not t.lane_tags(self.lanes)]

    def malformed(self) -> list[BoardTask]:
        """Tasks carrying two or more lane tags.

        A write would fail LANE_INVALID, so a human has to repair them.
        Surfaced so a board that looks idle can say why it isn't.
        """
        return [t for t in self.active_tasks
                if len(t.lane_tags(self.lanes)) > 1]

    def any_claim_live(self) -> bool:
        """True if any task on this board is claimed.

        The basis for one-task-in-flight-per-repo. We serialise per board
        because several tasks often touch the same files, and concurrent
        diffs collide. Lane membership alone can't answer this — a task can
        sit in an `agent` lane with an expired claim — which is exactly why
        the server hands us a per-task `claimed` flag.
        """
        return any(t.claimed for t in self.active_tasks)


def _lane_from(d: dict) -> Lane:
    return Lane(
        tag=d.get("tag", ""),
        label=d.get("label", ""),
        order=int(d.get("order", 0)),
        editable_by=d.get("editableBy", "user"),
        repo=(d.get("repo") or "").strip(),
    )


def _task_from(d: dict) -> BoardTask:
    return BoardTask(
        id=d.get("id", ""),
        title=d.get("title", ""),
        notes=d.get("notes") or "",
        tag=d.get("tag") or "",
        metadata=d.get("metadata") or {},
        claimed=bool(d.get("claimed")),
        status=_status_from(d.get("status")),
        state=d.get("state") or "Active",
        created_at=d.get("createdAt") or "",
        updated_at=d.get("updatedAt") or "",
        raw=d,
    )


#: Sentinel the far side only emits once autoland v3 is deployed. Chosen over
#: `status` or `laneKind` because it is an ERROR CODE: hadoku-task's
#: `openapi-verify` harness fails their build in both directions — a code they
#: emit that isn't enumerated, and an enumerated value nothing emits — so this
#: string cannot be in their published spec unless the code path that raises it
#: shipped with it.
_V3_SENTINEL = "NOTES_CHANGED"

#: Where that spec lives. Same origin as the board API, so a reachable board
#: implies a reachable spec.
OPENAPI_URL = "https://hadoku.me/task/api/openapi.json"


def far_side_has_v3(url: str = OPENAPI_URL, *, timeout: int = 15) -> Optional[bool]:
    """Is hadoku-task's v3 deployed? `None` when we could not find out.

    Three states, and collapsing the third into either of the others is the
    whole point of returning `Optional`:

      True   the spec enumerates NOTES_CHANGED — v3 is live.
      False  it does not — the worker is pre-v3, or has been rolled back.
      None   we could not read the spec. Not evidence of anything.

    **Why this is worth a network call at startup.** Driving a repo-laned board
    against a pre-v3 worker fails SILENTLY and expensively: unknown keys are
    stripped rather than refused, so every `status` we publish is discarded,
    every task reads back as having no chip, and selection re-plans all of them
    forever. Measured on the live v2 worker before their deploy — a release
    carrying `status` answered 200 and kept nothing.

    That is the one failure in this pipeline with no loud symptom at all, which
    makes it worth one GET per run to refuse instead. A v2 board is unaffected
    either way and keeps running.
    """
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "tenhands-taskauto/1.0"})
        if r.status_code != 200:
            logger.warning("could not read %s (HTTP %s)", url, r.status_code)
            return None
        return _V3_SENTINEL in r.text
    except requests.RequestException as e:
        logger.warning("could not read %s: %s", url, e)
        return None


def _ambient_key() -> str:
    """This service's hadoku identity, from `HADOKU_SERVICE_KEY`.

    One name, one identity, no fallback — and both halves of that are scar
    tissue.

    **The name.** This used to read `HADOKU_TASK_KEY`, which hadoku_site
    records as "only ever an alias for the existing `TENHANDS_SERVICE_KEY`".
    An alias is not free: it hides that a credential has an owner, and two
    names invite two values. `HADOKU_SERVICE_KEY` is what the pm2 wrapper
    already exports (`tenhands-wrapper.mjs`), so production, CI and local all
    now say the same word for the same thing.

    **The missing fallback.** It used to fall back to `.devvault.local.json`,
    on the reasoning that the file "holds the very same key". That stopped
    being true: that file holds the *vault caller* key, which is a different
    registered identity from the one holding the board shares. The fallback
    therefore authenticated successfully as the wrong service and reported
    an empty board list — indistinguishable from "nothing is shared with
    you". Failing loudly with no credential beats silently being someone
    else.
    """
    return os.environ.get("HADOKU_SERVICE_KEY", "").strip()


# ── Client ────────────────────────────────────────────────────────────────


class TaskBoardClient:
    """Client for one hadoku-task deployment.

    Auth is a **service-tier** hadoku key sent as `X-User-Key`, supplied via
    `HADOKU_SERVICE_KEY` and registered as **`tenhands-service-key`** (vault
    item `TENHANDS_SERVICE_KEY`). That identity is what board shares are
    granted to, and it is the *only* thing that decides which boards this
    client can see.

    **There were two keys for a while, and it cost an outage.** A second
    registered identity, `tenhands-service` (vault item
    `KEY_SERVICE_TENHANDS_SERVICE`), was this repo's vault caller and had
    historically held the board shares. When the shares moved, CI kept
    authenticating **successfully** as the older key and reported zero
    automation boards — a valid credential for the wrong identity, which
    reads exactly like "nothing is shared with you" and sends you looking at
    the sharing UI instead of the credential.

    Two lessons are baked into the code above: never alias this env var, and
    never fall back to another file for it. `.devvault.local.json` holds the
    vault caller, which is a different identity — reading it here is how the
    two got confused in the first place.

    **Where the tier comes from.** edge-router resolves the request tier from
    a service-tier record in the edge-router key registry
    (`authGate.ts::resolveCallerTier`) and stamps `X-Hadoku-Tier`; task-api
    trusts that header and never consults the key registry. So the 600/min
    bucket follows from that service-tier resolution, *not* from the
    `key:{rawKey}` registry row `POST /session/admin/keys` writes.

    That registry row is still needed, for a different reason: board sharing
    resolves a grantee to a `userId`, which is lazily minted on first sign-in
    (`upsertKeyRecord`). A key that has never signed in has none, so a board
    cannot be shared with it — surfacing here as `BOARD_NOT_FOUND`, not as a
    permissions error. Calling `POST /session/create` with the key once both
    mints that `userId` and sets the display name.
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        user_key: Optional[str] = None,
        timeout: int = 15,
        transport: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get(
            "HADOKU_TASK_API_URL", DEFAULT_BASE_URL)).rstrip("/")
        # `is None` rather than `or`: an explicit `user_key=""` means "no
        # credential" and must NOT fall through to the ambient one. With
        # `or`, a caller that deliberately passed no key would silently
        # authenticate as the real service account whenever the process
        # happened to have one — which is every vault-wrapped run, and is how
        # a keyless test started making authenticated calls.
        self.user_key = _ambient_key() if user_key is None else user_key
        self.timeout = timeout
        self._transport = transport or requests.request

    # ── plumbing ──────────────────────────────────────────────────────────

    def _call(self, method: str, path: str, *,
              json_body: Optional[dict] = None,
              params: Optional[dict] = None) -> dict:
        if not self.user_key:
            raise TaskBoardError(
                "No board credential. Set HADOKU_SERVICE_KEY to the "
                "`tenhands-service-key` value (vault item "
                "TENHANDS_SERVICE_KEY) — board shares are granted to that "
                "identity, and no other key can see them."
            )

        # Retry GETs, and ONLY GETs.
        #
        # `TaskBoardUnavailable` means we never got a verdict, and per this
        # module's contract the request "may or may not have been applied" — so
        # a write is not safe to repeat (a retried claim could double-apply, and
        # a timeout is exactly the case where the board may have processed it).
        # A GET has no such hazard.
        #
        # Worth doing because the sweep dies on its FIRST call. On 2026-08-10 a
        # single `GET /boards → HTTP 502` killed the whole run and burned the
        # cycle; the board was fine on the next attempt. That got more
        # expensive, not less, when the poll dropped to hourly (2026-09-04):
        # the next tick used to be 15 minutes away. Alerting
        # already debounces taskauto (monitoring-api ALERT_AFTER_CONSECUTIVE),
        # so this is about not throwing away a cycle, not about silencing pages.
        attempts = _GET_ATTEMPTS if method.upper() == "GET" else 1
        last: TaskBoardUnavailable | None = None
        for attempt in range(1, attempts + 1):
            try:
                return self._attempt(method, path, json_body=json_body, params=params)
            except TaskBoardUnavailable as e:
                last = e
                if attempt == attempts:
                    break
                delay = _GET_BACKOFF_S * attempt
                logger.warning(
                    "task board unavailable (%s), retrying in %ss "
                    "[attempt %d/%d]", e, delay, attempt, attempts,
                )
                time.sleep(delay)
        assert last is not None  # only reachable via the except branch
        raise last

    def _attempt(self, method: str, path: str, *,
                 json_body: Optional[dict] = None,
                 params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        try:
            resp = self._transport(
                method, url,
                json=json_body, params=params,
                headers={"X-User-Key": self.user_key},
                timeout=self.timeout,
            )
        except requests.Timeout as e:
            raise TaskBoardUnavailable(
                f"{method} {path} timed out after {self.timeout}s") from e
        except requests.RequestException as e:
            raise TaskBoardUnavailable(f"{method} {path} failed: {e}") from e

        return self._interpret(method, path, resp)

    def _interpret(self, method: str, path: str, resp: Any) -> dict:
        status = getattr(resp, "status_code", 0)
        try:
            body = resp.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {"data": body}

        if 200 <= status < 300:
            return body

        # 5xx is never a verdict — the board didn't decide, it fell over.
        if status >= 500:
            raise TaskBoardUnavailable(
                f"{method} {path} → HTTP {status}: {str(body)[:200]}")

        code = body.get("code") or ""
        message = body.get("error") or body.get("message") or f"HTTP {status}"

        cls = _ERRORS_BY_CODE.get(code)
        if cls is None and status == 429:
            # Older deployments answered 429 without a machine-readable code.
            cls = RateLimited
        if cls is None:
            logger.warning(
                "task-board %s %s → HTTP %d with unmapped code %r",
                method, path, status, code)
            raise TaskBoardDomainError(
                message, code=code, status=status, body=body)
        raise cls(message, code=code or cls.code, status=status, body=body)

    # ── reads ─────────────────────────────────────────────────────────────

    def get_board(self, ref: str) -> BoardSnapshot:
        """One board, fully hydrated: config, lanes, and tasks with claim flags.

        `ref` is a handle (a globally unique ULID) or the caller's own slug.
        Prefer the handle: slugs are display names and collide across users.
        """
        body = self._call("GET", f"/boards/{ref}")
        board = body.get("board") or {}
        lanes = [_lane_from(d) for d in (board.get("lanes") or [])]
        return BoardSnapshot(
            id=board.get("id", ""),
            name=board.get("name", ""),
            handle=board.get("handle", ""),
            repo=board.get("repo") or "",
            mode=board.get("mode", ""),
            lanes=sorted(lanes, key=lambda ln: ln.order),
            tasks=[_task_from(d) for d in (body.get("tasks") or [])],
            schema_id=board.get("schemaId") or "",
            schema_version=int(board.get("schemaVersion") or 0),
            access=board.get("access", ""),
            version=int(body.get("version") or 1),
        )

    def automation_boards(self) -> list[BoardSnapshot]:
        """Every automation board this key can drive, discovered not configured.

        A board is ours to work if it is shared with us (or owned by us),
        has been activated with a lane set, and **records a repo somewhere** —
        either the board-level scalar (v2, one repo per board) or on at least
        one lane (v3, a lane per repo). Nothing else needs saying: granting the
        key `contributor` on an automation board IS the act of enrolling it.

        The `or` in that sentence is load-bearing and was missing for three
        days. This filter required the board-level scalar, which a v3 board
        does not set — activation puts the repos on the lanes and leaves
        `boards.repo` null. So every v3 board was silently invisible: not an
        error, not a warning, just absent from discovery, and the runner would
        have reported "nothing to drive yet" forever no matter how many boards
        were activated. Caught by a production run, not by a test, because the
        end-to-end tests mocked this method.

        That is deliberately not a config list. A configured list has to be
        kept in step with reality by hand, and the failure when it drifts is
        silent — a board nobody notices is unwatched, or a stale handle the
        runner quietly idles against. Discovery cannot drift.

        **The returned snapshots carry no tasks, on purpose.** `GET /boards`
        does not populate the per-task `claimed` flag — only the hydrated
        `GET /boards/:ref` does — so a task list built from this endpoint
        would report every task as unclaimed whether or not one is live.
        A snapshot that looked identical to a hydrated one but lied about
        claim state is exactly the trap that produces a double-claim, so
        this returns identity and config only. Call `get_board(handle)` for
        anything that decides what to work on.
        """
        body = self._call("GET", "/boards")
        out: list[BoardSnapshot] = []
        for raw in (body.get("boards") or []):
            lanes = [_lane_from(d) for d in (raw.get("lanes") or [])]
            has_repo = bool((raw.get("repo") or "").strip()) or any(
                ln.is_repo_lane for ln in lanes)
            if not lanes or not has_repo:
                continue
            if raw.get("access") not in ("owner", "contributor"):
                continue
            out.append(BoardSnapshot(
                id=raw.get("id", ""),
                name=raw.get("name", ""),
                handle=raw.get("handle", "") or raw.get("id", ""),
                repo=raw.get("repo") or "",
                mode=raw.get("mode", ""),
                lanes=sorted(lanes, key=lambda ln: ln.order),
                tasks=[],  # see the docstring — this endpoint cannot say
                schema_id=raw.get("schemaId") or "",
                schema_version=int(raw.get("schemaVersion") or 0),
                access=raw.get("access", ""),
                version=int(raw.get("version") or 1),
            ))
        return out

    def history(self, board: str, task_id: str) -> list[dict]:
        """Claim history for one task — who held it, when, and each outcome."""
        body = self._call("GET", "/agent/history",
                          params={"board": board, "task": task_id})
        return body.get("history") or []

    def changes(self, since: Optional[str] = None, limit: int = 100) -> dict:
        """Cursor-based change feed. `since` is "<updatedAt>,<id>".

        Cheaper than re-reading whole boards once several are automated.
        Note it is scoped to the caller's own tasks, not to one board.
        """
        params: dict = {"limit": limit}
        if since:
            params["since"] = since
        return self._call("GET", "/changes", params=params)

    # ── claim protocol ────────────────────────────────────────────────────

    def claim(self, board: str, task_id: str, *, lane: Optional[str] = None,
              lease_seconds: Optional[int] = None,
              agent_id: Optional[str] = None) -> str:
        """Claim a task atomically; returns the lease token.

        Pass `lane` to move the task in the same write — always do this when
        claiming from the Inbox. An untagged task is in no lane, so the
        lane-based write protection that keeps humans out of `agent` lanes
        doesn't apply to it; moving it into an agent lane as part of the
        claim is what makes the work exclusively ours.

        Raises ClaimHeld if a live lease exists — expected, not an error.
        """
        body: dict = {"board": board, "taskId": task_id}
        if lane is not None:
            body["lane"] = lane
        if lease_seconds is not None:
            body["leaseSeconds"] = lease_seconds
        if agent_id:
            body["agentId"] = agent_id
        got = self._call("POST", "/agent/claim", json_body=body)
        token = got.get("token") or ""
        if not token:
            raise TaskBoardError(
                f"claim on {task_id} returned no token: {str(got)[:200]}")
        return token

    def heartbeat(self, board: str, task_id: str, token: str, *,
                  lease_seconds: Optional[int] = None) -> dict:
        """Extend the lease. Raises LeaseLost if the claim is no longer ours.

        This is also the cancel channel: when the board owner force-drops our
        claim, this is where we find out. Heartbeat on a cadence well inside
        the lease (default 30 min, max 1 h) so a cancel is noticed promptly
        rather than at the end of a long agent run.
        """
        body: dict = {"board": board, "taskId": task_id, "token": token}
        if lease_seconds is not None:
            body["leaseSeconds"] = lease_seconds
        return self._call("POST", "/agent/heartbeat", json_body=body)

    def set_lane(self, board: str, task_id: str, token: str, lane: str, *,
                 status: Optional[TaskStatus] = None) -> dict:
        """Move between lanes mid-job while holding the claim.

        `status` rides along so a long job can report progress **without
        releasing**. That matters more than it looks: releasing to report
        progress and re-claiming drops the lease in between, which is exactly
        the window another runner would take the task in.

        Omitting `status` leaves the chip alone; it is three-way like `notes`,
        so an unrelated lane move never silently wipes it.
        """
        body: dict = {"board": board, "taskId": task_id, "token": token,
                      "lane": lane}
        if status is not None:
            body["status"] = status.to_payload()
        return self._call("POST", "/agent/set-lane", json_body=body)

    def release(self, board: str, task_id: str, token: str, *,
                lane: Optional[str] = None, notes: Optional[str] = None,
                outcome: Optional[str] = None,
                metadata: Optional[dict] = None,
                complete: bool = False,
                status: Optional[TaskStatus] = None,
                if_current_lane: Optional[str] = None,
                if_notes_hash: Optional[str] = None) -> dict:
        """Release the claim, naming the destination lane.

        We choose where the task goes — the board holds no routing policy.
        `metadata`, `status` and `complete` are claim-gated: `complete: true`
        archives the task, which is how a finished task leaves the board
        instead of accumulating in a notification lane.

        **Two guards, and they cover different halves of the same hazard.**
        `if_current_lane` catches a human retagging mid-claim;
        `if_notes_hash` catches a human editing the plan mid-claim. Either
        mismatch writes nothing and raises — `LaneChanged`, `NotesChanged` —
        and in both cases **our token is still live**, so the caller has to
        hand the claim back rather than walk away (`RELEASE_ABORTED_CLAIM_HELD`).

        Pass `if_notes_hash` on every release that writes `notes`. Without it,
        a twenty-minute job ends by overwriting whatever the human typed while
        it ran, and the previous text was never stored anywhere — there is no
        recovery. Read-then-compare here cannot close that; only the board can
        compare and write in one operation.

        `NOTES_TOO_LARGE` **is** raised here — `releaseClaim` calls
        `assertNotesWithinLimit` before it reads or writes anything, so the
        64 KiB cap applies to the agent path too. (This docstring used to say
        the opposite, on a 2026-07-25 reading that the cap was on the human
        PATCH path only. It was true then and is not now.) Still don't code a
        truncate-and-retry: we keep notes small by rewriting rather than
        appending (see `plan_notes`), which is the real control.
        """
        body: dict = {"board": board, "taskId": task_id, "token": token}
        if lane is not None:
            body["lane"] = lane
        if notes is not None:
            body["notes"] = notes
        if outcome is not None:
            body["outcome"] = outcome
        if metadata is not None:
            body["metadata"] = metadata
        if complete:
            body["complete"] = True
        if status is not None:
            body["status"] = status.to_payload()
        if if_current_lane is not None:
            body["ifCurrentLane"] = if_current_lane
        if if_notes_hash is not None:
            body["ifNotesHash"] = if_notes_hash
        return self._call("POST", "/agent/release", json_body=body)

    # NOTE: POST /agent/cancel is deliberately not wrapped. It is owner-only
    # and would always 403 for our contributor key. It exists for the human
    # to stop us; we observe it as LeaseLost on the next heartbeat.
