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

import logging
import os
from dataclasses import dataclass, field
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


_ERRORS_BY_CODE: dict[str, type[TaskBoardDomainError]] = {
    cls.code: cls
    for cls in (
        ClaimHeld, LeaseLost, LaneUnknown, LaneNotEditable, LaneInvalid,
        LaneChanged, TaskNotFound, BoardNotFound, VersionConflict,
        NotesTooLarge, Forbidden, RateLimited,
    )
}


# ── Board shapes ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Lane:
    tag: str
    label: str
    order: int
    editable_by: str  # "user" | "agent"

    @property
    def is_agent(self) -> bool:
        return self.editable_by == "agent"


@dataclass(frozen=True)
class BoardTask:
    id: str
    title: str
    notes: str
    tag: str  # space-separated tag string; the lane is a token within it
    metadata: dict
    claimed: bool
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

        Tags are one space-separated string, not an array, and a user is
        free to add their own (`urgent`, `someday`) alongside a lane tag.
        So "has no lane" and "has no tags" are different questions, and
        conflating them strands any task the human labelled by hand.
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
    )


def _task_from(d: dict) -> BoardTask:
    return BoardTask(
        id=d.get("id", ""),
        title=d.get("title", ""),
        notes=d.get("notes") or "",
        tag=d.get("tag") or "",
        metadata=d.get("metadata") or {},
        claimed=bool(d.get("claimed")),
        state=d.get("state") or "Active",
        created_at=d.get("createdAt") or "",
        updated_at=d.get("updatedAt") or "",
        raw=d,
    )


# ── Client ────────────────────────────────────────────────────────────────


class TaskBoardClient:
    """Client for one hadoku-task deployment.

    Auth is a service-tier key sent as `X-User-Key`. The key must be
    registered as `tier: "service"` on the board side to get the 600/min
    throttle; a mis-tiered key silently degrades to the 60/min public tier
    and then gets blacklisted after three violations.
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
        self.user_key = user_key or os.environ.get("HADOKU_TASK_KEY", "")
        self.timeout = timeout
        self._transport = transport or requests.request

    # ── plumbing ──────────────────────────────────────────────────────────

    def _call(self, method: str, path: str, *,
              json_body: Optional[dict] = None,
              params: Optional[dict] = None) -> dict:
        if not self.user_key:
            raise TaskBoardError(
                "HADOKU_TASK_KEY is not set. This is a service-tier key issued "
                "by the hadoku-task operator and declared in .devvault.json; "
                "fetch it via dev-vault.mjs rather than hardcoding it."
            )
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

    def set_lane(self, board: str, task_id: str, token: str, lane: str) -> dict:
        """Move between lanes mid-job while holding the claim."""
        return self._call("POST", "/agent/set-lane", json_body={
            "board": board, "taskId": task_id, "token": token, "lane": lane,
        })

    def release(self, board: str, task_id: str, token: str, *,
                lane: Optional[str] = None, notes: Optional[str] = None,
                outcome: Optional[str] = None,
                metadata: Optional[dict] = None,
                complete: bool = False,
                if_current_lane: Optional[str] = None) -> dict:
        """Release the claim, naming the destination lane.

        We choose where the task goes — the board holds no routing policy.
        `metadata` and `complete` are claim-gated: `complete: true` archives
        the task, which is how `landed` avoids growing without bound.

        `if_current_lane` guards against a human retagging mid-claim; a
        mismatch raises LaneChanged and writes nothing.
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
        if if_current_lane is not None:
            body["ifCurrentLane"] = if_current_lane
        return self._call("POST", "/agent/release", json_body=body)

    # NOTE: POST /agent/cancel is deliberately not wrapped. It is owner-only
    # and would always 403 for our contributor key. It exists for the human
    # to stop us; we observe it as LeaseLost on the next heartbeat.
