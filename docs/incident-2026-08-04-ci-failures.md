# Incident: taskauto run died with its runner — 1 failure (2026-08-04)

> **Verified 2026-08-05 from hokon itself** (runner `_diag` logs, the kernel
> journal, `~/.pm2/pm2.log`, and `/health/api/jobs`). This replaces an earlier
> draft written from outside, which guessed at a network cause. That guess was
> wrong; the corrected chain is below, with the evidence for each link.

## What happened

`tenhands / Task automation` run **30950996997** started 2026-08-04 21:07:44
UTC on `hokon-tenhands` and was killed at **21:25:05 UTC**, ~17 minutes in,
during the "Run the pipeline" step. Its logs were never uploaded because the
runner process ceased to exist mid-job.

**Root cause: a host-wide out-of-memory event on hokon, not a network fault.**
taskauto was collateral damage, not the cause.

## The actual chain

1. **ComfyUI ate the box.** pid 892674 —
   `hadoku-conjure/backend/.venv/bin/python main.py --listen 127.0.0.1 --port 8188`,
   spawned under the `conjure` pm2 app — reached **51.3 GB anon-RSS / 127 GB
   total-vm** on a 61 GB host. The kernel fired a **global** OOM kill
   (`constraint=CONSTRAINT_NONE`, `global_oom`) and reaped it:

   ```
   kernel: Out of memory: Killed process 892674 (python) total-vm:127558268kB,
           anon-rss:51340956kB ... oom_score_adj:0
   kernel: oom-kill:constraint=CONSTRAINT_NONE,...,global_oom,
           task_memcg=/system.slice/pm2-hadoku.service,task=python,pid=892674
   ```

   Corroborating: conjure's node shim is pid 892652 (logged 14:00:16 PDT), 22
   pids below the victim, and at the moment of the kill it logged
   `proxy error: connect ECONNREFUSED 127.0.0.1:8188` — its Python backend had
   just vanished.

2. **`OOMPolicy=stop` turned one dead process into a whole-host outage.** The
   victim lived in the `pm2-hadoku.service` cgroup. systemd's default
   `OOMPolicy=stop` means *any* OOM kill inside a unit stops the **entire
   unit** — so systemd ran `ExecStop=pm2 kill` and took down **all 23 pm2
   apps**, `github-runner-tenhands` among them:

   ```
   systemd[1]: pm2-hadoku.service: A process of this unit has been killed by the OOM killer.
   pm2.log:    2026-08-04T14:25:06: PM2 log: Stopping app:github-runner-tenhands id:17
   systemd[1]: pm2-hadoku.service: Failed with result 'oom-kill'.
   systemd[1]: pm2-hadoku.service: Consumed ... 50.4G memory peak, 28.6G memory swap peak.
   ```

3. **The runner died of SIGINT, and said so in a way that reads like a network
   fault.** `Restart=on-failure` then resurrected pm2, and the runner was back
   at 21:25:13 — seven seconds later.

## Correcting the earlier draft

- **"The runner lost its GitHub connection" — no.** The
  `BrokerServer SocketException (125)` is errno **ECANCELED**: the runner
  cancelling *its own* in-flight long-poll as it shut down. It is a symptom of
  the local SIGINT, not a cause. Same for the `renewjob` 404 (the job was
  already gone) and `Runner will be shutdown for UserCancelled`. Reading that
  stack as a disconnect inverts cause and effect.
- **"Network/DNS on hokon has a history — check split-DNS and Tailscale" — a
  dead end here.** Nothing in this chain is network. Don't spend time there.
- **"Is this disconnect recurring?" — no.** This is the **only** global OOM in
  the current boot (since 2026-07-29). Every other OOM in the journal is
  `CONSTRAINT_MEMCG`, contained inside a memory-capped cgroup — see below.
- **"Verify the predecessor-reporter upserted `gha_30950996997`" — it could not
  have, and the absence proves nothing.** The record is genuinely missing from
  `/health/api/jobs`, but the reporter step landed in `d598854` at
  **2026-08-04 22:17:51 UTC — 52 minutes after the run died**. It did not exist
  yet. The mitigation has no hole; it simply postdates the incident.

  Checked against this exact scenario, it *would* have fired: GitHub marked the
  dead run `completed/failure` at 21:25:05, and the next run's first step ran
  at 21:25:16 — eleven seconds later, well inside the window.
- **"Did the interrupted run leave bad state behind?" — no.** The next run
  (30951526189) began a clean `actions/checkout` at 21:25:16, held no stale
  lock, and concluded `success` at 21:29:11.

## What taskauto already does right — and it is the fix everyone else needs

`backend/temporal/taskauto/proc.py` runs every subprocess tree under
`systemd-run --user --scope` with `MemoryMax`, `MemorySwapMax=0`, and
`RuntimeMaxSec`. Its own docstring states the goal: *"the tree dies instead of
the host."*

That is not theoretical. The `CONSTRAINT_MEMCG` OOMs in the journal on
2026-07-29 are `taskauto-test-*.scope` and `taskauto-typecheck-*.scope` hitting
their caps — the mechanism working exactly as designed: contained, host
unharmed, nothing else noticed.

The runner reinforces it: it sets `oom_score_adj=500` on job processes, making
them the *preferred* victim. In the 21:25 dump the taskauto processes carry adj
500 and were **not** chosen; the 51 GB ComfyUI at adj 0 was. taskauto was the
best-behaved workload on the box and still got killed, because the thing that
killed it was two layers above it.

## Open items — both outside this repo

1. **`OOMPolicy=continue` on `pm2-hadoku.service`** (owner: hadoku_site). For a
   process supervisor whose entire job is running independent children, the
   systemd default is a footgun: one child's OOM stops all 23. With
   `continue`, systemd leaves the unit alone and pm2 restarts just the app that
   died. Blast radius goes from the fleet to one service. **Not applied — this
   is a live host-wide systemd change and needs an operator's call.**
2. **A memory ceiling on the conjure/ComfyUI backend** (owner: hadoku-conjure
   / hadoku_site). It currently runs uncapped in the shared pm2 cgroup
   (`MemoryMax=infinity`). `proc.py` in this repo is the working model.

Memory pressure on hokon is ongoing, not resolved: at the time of writing the
host sits at 35/61 GB RAM and 21/31 GB swap, with an `invokeai-web` python
holding 8.6 GB. Until item 1 lands, the next uncapped balloon takes the fleet
down the same way.
