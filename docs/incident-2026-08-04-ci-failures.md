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

## Resolution

### Update, 2026-08-05: both open items are closed

**`pm2-hadoku.service` is capped and no longer amplifies.** Current state:

```
MemoryHigh=20G   MemoryMax=32G   MemorySwapMax=4G   OOMPolicy=continue
```

The fleet-amplifier argument below is **resolved**. With `OOMPolicy=continue`
systemd no longer stops the unit when a process inside it is OOM-killed, so the
blast radius is 1 app rather than 23 — the "same amplifier, a third of the
trigger" regression no longer applies. The note about `systemctl set-property`
rejecting `OOMPolicy` is correct and load-bearing: the three resource-control
properties live in `/etc/systemd/system.control/pm2-hadoku.service.d/`, while
`OOMPolicy` needed a hand-written drop-in at
`/etc/systemd/system/pm2-hadoku.service.d/oom.conf` (applied 14:38 PDT via
`~/security/fix-pm2-oom-policy.sh`).

The ceiling was raised from the 16G/24G above to 20G/32G. The first sizing was
taken from a `MemoryPeak` of 5.68 GB, which understated real load: `MemoryPeak`
is a high-water mark since the cgroup was created, and pm2 had been restarted an
hour earlier. The same counter read **11.04 GB** an hour later under ordinary
concurrent CI. Size against a peak measured after a busy period, never a fresh
one.

**Item 2 (a ceiling on the ComfyUI backend) is closed — but the fix was not
where it looked.**

`backend/launch_comfyui.sh` had already grown the containment on 2026-08-05: its
own `systemd-run --user --scope` with `MemoryMax=48G`, `MemorySwapMax=4G`, and
`oom_score_adj=700`. It was not taking effect. The engine kept running at
`oom_score_adj=0` inside `/system.slice/pm2-hadoku.service`.

The cause is `scripts/restart-backend.py`, conjure's `postDeployCommand`. It
relaunches the engine by cloning the live process's **argv, cwd and environment**
out of `/proc` — and a cgroup and `oom_score_adj` are in none of those. So every
conjure deploy silently relaunched ComfyUI with no ceiling, in whatever cgroup
the deploy step occupied (mgmt-api's, i.e. pm2's). One correct start via the
launch script was undone by the very next deploy, and nothing logged it.

Fixed in `hadoku-conjure` `b967bf0`: `start()` re-applies both layers, mirroring
the launch script so the two entry points cannot drift. Verified live — ComfyUI
now runs at `adj=700` with `memory.max=48G` in its own `run-p*.scope`, outside
`pm2-hadoku.service` entirely.

A detail worth keeping: the engine's environment carried `CLAUDECODE`/`TMUX`
variables cloned forward from a single hand launch many restarts earlier. Those
fossils are what proved the engine had originally been started outside the
script — not evidence of repeated hand starts.

**Related, same root:** the two Actions runners left pm2 for
`github-runner.service` / `github-runner-tenhands.service` in `ci-runner.slice`
(`hadoku_site` `50f426f5`). CI did not cause this incident, but it sat in the
same unbounded cgroup and is the likelier future offender.

### Still open

**InvokeAI is the last uncontained GPU engine.** `~/apps/invoke/*.sh` set no
scope, no `MemoryMax` and no `oom_score_adj`; it currently runs at `adj=200`
with `memory.max=max`. Conjure's scripts already assume a ladder of
`invoke=800 > conjure=700 > taskauto jobs=500` — nothing implements the 800.
`backend/temporal/taskauto/proc.py` in this repo remains the working model.

**Detection now exists.** `hadoku_site`'s sitrep asserts containment rather than
only watching growth: `collectEngineContainment` reads each known engine's real
`memory.max` and `oom_score_adj` and warns when either is missing. It reads the
actual cgroup limit rather than inferring from the cgroup's name — an earlier
revision tested for a `*.scope` suffix and passed InvokeAI, which runs in
`tmux-spawn-*.scope`: a real scope by name, `MemoryMax=infinity`, eight
unrelated processes in it.

## Historical: the fleet-amplifier analysis (superseded by OOMPolicy=continue)

> Kept because the reasoning is still the right way to think about a cap on a
> unit with `OOMPolicy=stop`, and because it is what motivated the fix. **The
> numbers and the `OOMPolicy=stop` premise below are as-of 2026-08-05 14:26 PDT
> and no longer describe the host** — see Resolution above for current state.

`pm2-hadoku.service` has been bounded (`fix-pm2-memory-cap.sh`, applied 14:26
PDT, persistent drop-in under `/etc/systemd/system.control/`):

```
MemoryHigh=16G   MemoryMax=24G   MemorySwapMax=4G   OOMPolicy=stop  ← unchanged
```

That is a real win for the **host**: pm2's balloons can no longer starve
`invokeai-web`, the desktop session, or anything else outside the cgroup, and
`MemoryHigh=16G` adds a reclaim brake that should absorb slow growth without
killing anything.

For the **fleet** it is a regression, because `OOMPolicy` was not touched:

| | fleet-wide outage triggers when… |
|---|---|
| before the cap | the whole host exhausts — ~61 GB RAM + 31 GB swap |
| after the cap | pm2's cgroup alone exceeds **24 GB + 4 GB swap** |

Same amplifier, roughly a third of the trigger. Every balloon between 24 GB and
~92 GB that previously would *not* have taken the fleet down now will. The cap
fixed the trigger; the blast radius is untouched.

Current headroom, for calibration: the cgroup sits at **4.9 GB** with an
**11.0 GB peak** over the ~23 h since the Aug 4 restart, so the cap will not
fire in normal operation — it only fires on a genuine balloon, and when it does
it still takes all 23 apps with it. `memory.events` is all zeros so far, and
`memory.oom.group=0`, so a kill claims one process rather than the whole cgroup.

### The two open items as filed (both now closed — see Resolution)

1. **`OOMPolicy=continue` on `pm2-hadoku.service`** (owner: hadoku_site).
   Now the missing half of a change already made, not optional hardening. With
   `continue`, systemd leaves the unit alone and pm2 restarts just the app that
   died — blast radius 1 instead of 23, which is the entire point of running a
   supervisor. It makes systemd do strictly *less*, so it cannot itself cause an
   outage, and it needs no restart: `OOMPolicy` is read when the OOM event is
   handled, so `daemon-reload` suffices.

   Note it **cannot** be applied with `systemctl set-property` — `OOMPolicy` is
   a service property, not a resource-control one, and set-property rejects it
   ("Cannot set property OOMPolicy, or unknown property"). It needs a real
   drop-in. Ready to run: `~/security/fix-pm2-oom-policy.sh`.
2. **A memory ceiling on the conjure/ComfyUI backend** (owner: hadoku-conjure
   / hadoku_site). Still uncapped *individually* — the new 24 GB ceiling is
   shared across all 23 apps, so ComfyUI can still consume the whole budget and
   starve its neighbours out of it. `proc.py` in this repo is the working model
   for a per-workload cap.

Memory pressure on hokon is real but no longer unbounded: at the time of writing
the host sits at 23/61 GB RAM and 12/31 GB swap, with every engine except
InvokeAI now carrying its own ceiling.
