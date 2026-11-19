"""A stand-in for crossposter's Claude Code lease routes, over real HTTP.

Serves `POST /claude-code/lease` and `POST /claude-code/lease/outcome` the way
crossposter does (hadoku-crossposter `control/claude_code_pool.py`): the active
account is the first one not benched; a `rate_limited` or `unauthorized`
outcome benches the lease's account and re-decides; `ok` lifts its bench. It
answers on a real socket so the lease client's own HTTP code runs, headers and
all, rather than a patched function.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class FakeCrossposter:
    #: account name -> token, in the order crossposter would prefer them.
    accounts: dict[str, str]
    key: str = "test-service-key"
    benched: dict[str, str] = field(default_factory=dict)  # name -> why_not
    #: Answer every lease with this status instead (403: not on the allow list).
    refuse: int | None = None
    leases: list[dict] = field(default_factory=list)
    outcomes: list[dict] = field(default_factory=list)
    user_agents: list[str] = field(default_factory=list)
    url: str = ""

    def active(self) -> str | None:
        return next((a for a in self.accounts if a not in self.benched), None)

    # ── server ────────────────────────────────────────────────────────────

    def start(self) -> FakeCrossposter:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep pytest output clean
                pass

            def _send(self, status: int, body: object) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                fake.user_agents.append(self.headers.get("User-Agent", ""))
                if self.headers.get("X-User-Key") != fake.key:
                    return self._send(403, {"error": "forbidden", "required": "service"})
                if self.path == "/claude-code/lease":
                    return self._send(*fake._lease())
                if self.path == "/claude-code/lease/outcome":
                    return self._send(*fake._outcome(body))
                return self._send(404, {"error": "not found"})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01},
                         daemon=True).start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    # ── routes ────────────────────────────────────────────────────────────

    def _lease(self) -> tuple[int, dict]:
        if self.refuse:
            return self.refuse, {"error": "forbidden", "required": "service"}
        active = self.active()
        if active is None:
            return 503, {"detail": {
                "error": "no Claude Code account can be leased",
                "reason": "no account is usable",
                "accounts": [{"name": a, "why_not": self.benched[a]} for a in self.accounts],
            }}
        lease = {"lease_id": uuid.uuid4().hex, "account": active,
                 "vault_item": f"CLAUDE_OAUTH_TOKEN_{active.upper()}",
                 "token": self.accounts[active], "expires_at": "2026-11-18T13:00:00+00:00"}
        self.leases.append(lease)
        return 200, lease

    def _outcome(self, body: dict) -> tuple[int, dict]:
        lease = next((x for x in self.leases if x["lease_id"] == body.get("lease_id")), None)
        if lease is None:
            return 404, {"detail": f"no lease {body.get('lease_id')!r}"}
        self.outcomes.append({"account": lease["account"], "outcome": body["outcome"]})
        benched = body["outcome"] in ("rate_limited", "unauthorized")
        if benched:
            code = 429 if body["outcome"] == "rate_limited" else 401
            self.benched[lease["account"]] = f"benched: HTTP {code} on lease {lease['lease_id']}"
        elif body["outcome"] == "ok":
            self.benched.pop(lease["account"], None)
        return 200, {"lease_id": lease["lease_id"], "account": lease["account"],
                     "outcome": body["outcome"], "benched": benched, "active": self.active()}
