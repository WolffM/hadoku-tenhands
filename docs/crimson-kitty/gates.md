# Gates

Every check that decides whether an issue advances is a **gate**. Gates are
declared in one registry and run by the orchestrator after every state
transition. They are pure functions over the evidence store.

## Design constraint: judge does minimal work

Per F1: **the judge runs at most twice per issue, total**. The pipeline is
NOT a sequence of LLM-scored checkpoints. It's a sequence of mechanical
gates with a few semantic gates surgically placed where mechanics can't
reach.

Concretely:

- **Mechanical gates** are the default. They cover presence, format,
  diff size, file lists, ref scans, template structure, etc. They run on
  every issue and never need a judge call.
- **Judge gates** run only at two points: once after `fixed` (relevance
  check — "do the changed files make sense for this issue") and once
  after `submittable` (consolidated PR-quality check — "is this PR ready
  for human eyes"). That's it.
- `repro_quality` is **dropped** as a judge gate; replaced with a stronger
  mechanical check (presence + word count + section structure of
  `notes.md`).
- `pr_body_quality` is **merged** into a single `submission_judge` gate
  that scores PR body quality, template compliance commentary, and
  AI-tell detection in one call — saving one judge invocation per issue.

Per-issue judge call budget: **2 calls** (one canary at boot of activity,
one real). Per 50-issue batch: **~100 judge calls**, ~50 minutes total
wall time at 30s/call, single-threaded — well within Max usage limits
even with the canary doubling the count.

## Gate kinds

- **mechanical** — deterministic. Runs without LLM calls. Examples: "diff is
  non-empty," "no upstream refs in the title."
- **judge** — calls an LLM judge with the evidence and a rubric. Returns a
  confidence score and reasoning. Auto-passes above threshold, defers
  below.
- **human** — always defers to the operator. Used sparingly, for irreversible
  actions like the final upstream submit.

## Gate result type

```python
@dataclass
class GateResult:
    verdict: Literal["pass", "fail", "defer"]
    reason: str
    evidence_path: str | None  # path to a JSON blob with details
    score: float | None        # for judge gates, 0.0-1.0

# Pass:  verdict="pass"
# Fail:  verdict="fail",  reason="...", evidence_path="..."
# Defer: verdict="defer", reason="...", evidence_path="..."  (queues for human)
```

## The registry

Each gate is mapped to the bug class from `jade-hare` it kills. The bugs
reference the retro analysis in `docs/crimson-kitty/README.md`.

### `eligibility`

**Kind**: mechanical
**Runs after**: `candidate`
**Kills**: hostile-repo dispatches (uptime-kuma "AI-policy non-negotiable"
class), already-claimed issues (opentofu#3864), wrong-language scope (vcpkg
matplotlib).

```python
@gate(after=State.CANDIDATE, kind="mechanical")
def eligibility(issue, evidence) -> GateResult:
    dossier = evidence.read_json("01-eligible/dossier.json")
    brief   = evidence.read_json("01-eligible/issue_brief.json")
    contrib = evidence.read_json("01-eligible/contributing_check.json")

    if contrib.get("ai_policy") == "banned":
        return Fail("repo CONTRIBUTING.md bans AI-generated PRs",
                    evidence="01-eligible/contributing_check.json")
    if brief["issue"].get("assignee"):
        return Fail(f"already assigned to {brief['issue']['assignee']}")
    if brief["issue"].get("state") != "open":
        return Fail("issue is closed")
    health = dossier["health"]
    if health.get("activity_score", 0) < 0.3:
        return Fail("repo activity below threshold (likely abandoned)")
    return Pass()
```

### `input_context_clean`

**Kind**: mechanical
**Runs after**: `forked`
**Kills**: the input-side leak class — any case where the agent's brief
still contains a real upstream URL/slug/issue number after the scrubber
runs (mermaid#4099 class — Copilot was given the upstream number and
echoed it).

```python
@gate(after=State.FORKED, kind="mechanical")
def input_context_clean(issue, evidence) -> GateResult:
    brief = evidence.read_text("02-forked/scrubbed_brief.md")

    upstream  = issue.upstream_slug          # e.g. "microsoft/markitdown"
    issue_num = str(issue.upstream_number)   # e.g. "183"

    leaks = []
    leaks += scan_for_url(brief, upstream)
    leaks += scan_for_short_ref(brief, upstream)
    leaks += scan_for_keyword_ref(brief, issue_num)
    if upstream in brief:
        leaks.append(f"bare upstream slug present: {upstream}")

    if leaks:
        return Fail(
            f"scrubbed brief still contains upstream refs: {leaks}",
            evidence="02-forked/scrubbed_brief.md",
        )
    return Pass()
```

The branch name is not checked here — branches are operator-controlled and
descriptive (`fix-blank-cells-xlsx`). Branch-level leaks are caught by the
output sanitizer at the `submittable → submitted` transition along with
title/body/commit refs.

### `environment_works`

**Kind**: mechanical
**Runs after**: `environment_ready`
**Kills**: dispatches that fail at clone/install (Bucket A from jade-hare —
the 10 issues that never started).

```python
@gate(after=State.ENVIRONMENT_READY, kind="mechanical")
def environment_works(issue, evidence) -> GateResult:
    health = evidence.read_json("03-environment/health.json")
    if not health.get("installable"):
        return Fail("dependencies failed to install",
                    evidence="03-environment/install_log.txt")
    return Pass()
```

### `repro_evidence_present`

**Kind**: mechanical (presence + structure)
**Runs after**: `reproduced`
**Kills**: claimed fixes without verified reproduction (puppeteer saga).

Stronger mechanical check replaces the judge-based `repro_quality`. We
verify presence, then verify `notes.md` has structure and substance via
mechanical word-count + section detection.

```python
@gate(after=State.REPRODUCED, kind="mechanical")
def repro_evidence_present(issue, evidence) -> GateResult:
    repro_dir = evidence.dir("04-reproduced")
    if not repro_dir.exists():
        return Fail("no reproduced/ directory created")

    has_test    = any(repro_dir.glob("test.*"))
    has_image   = (repro_dir / "before.png").exists()
    has_trace   = (repro_dir / "trace.zip").exists()
    notes_path  = repro_dir / "notes.md"

    if not (has_test or has_image or has_trace):
        return Fail("no test, screenshot, or trace produced")
    if not notes_path.exists():
        return Fail("notes.md missing — agent must explain the repro")

    # Structural checks on notes.md (no LLM call).
    notes = notes_path.read_text()
    if len(notes.split()) < 50:
        return Fail(f"notes.md too short ({len(notes.split())} words)")
    required = ["## Steps to reproduce", "## Observed", "## Expected"]
    missing = [s for s in required if s not in notes]
    if missing:
        return Fail(f"notes.md missing sections: {missing}")
    return Pass()
```

The agent is told upfront in its instructions to write `notes.md` with
the required sections and at least 50 words. Mechanical enforcement, no
judge needed.

### `diff_non_empty`

**Kind**: mechanical
**Runs after**: `fixed`
**Kills**: empty PRs — the **highest-ROI gate**, kills 21% of jade-hare's
upstream PRs by itself (keras#22455, solidjs#2640, grafana#120769,
podman#28330, esbuild#4422, payload#16008).

```python
@gate(after=State.FIXED, kind="mechanical")
def diff_non_empty(issue, evidence) -> GateResult:
    diff = evidence.read_text("05-fixed/diff.patch")
    shas = evidence.read_text("05-fixed/commit_shas.txt").strip().splitlines()

    if not diff.strip():
        return Fail("diff is empty — no commits ahead of base")
    if not shas:
        return Fail("no commit SHAs recorded")
    if len(diff) < 50:
        return Fail(f"diff suspiciously short ({len(diff)} bytes)")
    return Pass()
```

### `relevance`

**Kind**: judge
**Runs after**: `fixed`
**Kills**: agents touching unrelated files (markitdown unrelated import
cleanup class).

```python
@gate(after="fixed", kind="judge")
def relevance(evidence) -> GateResult:
    files      = evidence.read_lines("05-fixed/files_touched.txt")
    issue_body = evidence.read_json("01-eligible/issue_brief.json")["issue"]["body"]

    payload = {
        "issue_body": issue_body[:1000],
        "files_touched": files,
    }
    try:
        from ..judge import score
        r = score(payload, rubric="relevance_v1")
    except Exception as e:
        # JudgeUnreachable | JudgeParseError | timeout — defer with system: prefix
        return Defer("relevance", f"system:{type(e).__name__}: {e}")

    if r.score < 0.6:
        return Defer("relevance",
                     f"low relevance (score={r.score:.2f})",
                     evidence_data={"score": r.score, "reasoning": r.reasoning})
    return Pass("relevance", score=r.score)
```

The rubric lives at `backend/temporal/rubrics/relevance_v1.md` — not
inline. This makes it editable without code changes and lets us version
rubrics independently of pipeline logic.

### `verified_evidence_present`

**Kind**: mechanical (visual diff is pixel-comparison, not LLM)
**Runs after**: `verified`
**Kills**: "claimed fix that doesn't actually fix anything" (puppeteer
"Not working" ×5 class).

```python
@gate(after=State.VERIFIED, kind="mechanical")
def verified_evidence_present(issue, evidence) -> GateResult:
    test_out = evidence.read_text("06-verified/test_output.txt", default="")
    after    = evidence.path("06-verified/after.png")

    if test_out and "passed" in test_out.lower():
        return Pass()
    if after.exists():
        # Check there's a corresponding before.png and they differ visually.
        before = evidence.path("04-reproduced/before.png")
        if not before.exists():
            return Fail("after.png exists but no before.png to compare")
        score = visual_diff(before, after)
        if score < 0.05:  # <5% pixel diff
            return Fail(f"before/after visually identical (diff={score:.3f})")
        return Pass()
    return Fail("no passing test output and no after.png")
```

### `remediation_complete`

**Kind**: mechanical
**Runs after**: `remediated`

```python
@gate(after=State.REMEDIATED, kind="mechanical")
def remediation_complete(issue, evidence) -> GateResult:
    resolved = evidence.read_json("08-remediated/resolved_comments.json")
    review   = evidence.read_json("07-reviewed/comments.json")

    blocking = [c for c in review if c["severity"] == "blocking"]
    unaddressed = [c for c in blocking if c["id"] not in resolved]

    if unaddressed:
        return Fail(f"{len(unaddressed)} blocking comments unaddressed")
    return Pass()
```

### `no_upstream_refs`

**Kind**: mechanical
**Runs after**: `submittable`
**Kills**: cross-reference leaks (markitdown#183, mermaid#4099,
hoppscotch#3331).

```python
@gate(after=State.SUBMITTABLE, kind="mechanical")
def no_upstream_refs(issue, evidence) -> GateResult:
    title = evidence.read_text("09-submittable/pr_title.txt")
    body  = evidence.read_text("09-submittable/pr_body.md")
    diff  = evidence.read_text("05-fixed/diff.patch")

    upstream = issue.upstream_slug
    upstream_num = issue.upstream_number

    leaks = []
    leaks += scan_for_url(title + body, f"github.com/{upstream}")
    leaks += scan_for_short_ref(title + body, upstream, upstream_num)
    leaks += scan_for_keyword_ref(title + body, upstream_num)  # Fixes #N, Closes #N
    # Also scan commit messages, since GitHub indexes those too.
    leaks += scan_commit_messages(diff, upstream, upstream_num)

    if leaks:
        return Fail(
            f"{len(leaks)} upstream refs detected",
            evidence_data={"leaks": leaks},
        )
    return Pass()
```

### `pr_template_compliance`

**Kind**: mechanical
**Runs after**: `submittable`
**Kills**: PR-template violations (uptime-kuma "PR template is non-negotiable
due to AI-policy" class).

```python
@gate(after=State.SUBMITTABLE, kind="mechanical")
def pr_template_compliance(issue, evidence) -> GateResult:
    body     = evidence.read_text("09-submittable/pr_body.md")
    template = evidence.read_json("01-eligible/dossier.json")["pr_template"]

    required_sections = template.get("sections", [])
    missing = []
    for section in required_sections:
        if section.get("required") and section["heading"] not in body:
            missing.append(section["heading"])
    if missing:
        return Fail(f"missing template sections: {missing}")
    return Pass()
```

### `submission_judge` (consolidated)

**Kind**: judge — **THE primary judge call of the pipeline**
**Runs after**: `submittable` (the second of two judge calls per issue;
the first is `relevance` after `fixed`)

Replaces the old `pr_body_quality` gate. Scores the entire submission in
one pass: PR body quality, AI-tell detection, problem-fix-verify
narrative completeness, and a sanity check that the body is consistent
with the diff.

This is the **last quality check before public submission** and the only
LLM-based gate at this state. All other submission-state gates
(`no_upstream_refs`, `pr_template_compliance`) are mechanical.

```python
@gate(after=State.SUBMITTABLE, kind="judge")
def submission_judge(issue, evidence) -> GateResult:
    body          = evidence.read_text("09-submittable/pr_body.md")
    diff_summary  = evidence.read_text("05-fixed/files_touched.txt")
    issue_brief   = evidence.read_json("01-eligible/issue_brief.json")
    repro_notes   = evidence.read_text("04-reproduced/notes.md")

    payload = {
        "issue_title":    issue_brief["issue"]["title"],
        "issue_body":     issue_brief["issue"]["body"][:1500],
        "files_touched":  diff_summary.splitlines(),
        "repro_notes":    repro_notes,
        "pr_body":        body,
    }

    from ..judge import score
    s, reasoning = score(payload, rubric="submission_v1")

    if s < 0.6:
        return Defer("submission_judge",
                     f"low submission quality (score={s:.2f})",
                     evidence_data={"score": s, "reasoning": reasoning})
    if s < 0.75:
        return Defer("submission_judge",
                     f"borderline submission quality (score={s:.2f})",
                     evidence_data={"score": s, "reasoning": reasoning})
    return Pass("submission_judge", score=s)
```

The `submission_v1` rubric (lives at `backend/temporal/rubrics/submission_v1.md`)
asks the judge to score on five axes, return one combined score, and one
paragraph of reasoning:

1. **Narrative completeness**: does the body have problem / repro / fix /
   verification sections?
2. **Diff-body consistency**: do the files mentioned in the body match
   the files actually touched?
3. **AI-tell density**: phrases like "I have made the following changes",
   "this PR aims to", excessive markdown headers
4. **Repro-fix linkage**: does the body reference the repro evidence?
5. **Honesty**: does the body claim things the diff doesn't support?

## Bug → gate mapping (jade-hare retrospective)

| jade-hare bug class | Kills it |
|---|---|
| Cross-reference leaks (markitdown, mermaid, hoppscotch) | `input_context_clean` (mechanical, primary — agent never sees the real ref) + `no_upstream_refs` (mechanical, defense in depth at submission) |
| Empty PRs (≥6 confirmed) | `diff_non_empty` (mechanical) |
| AI-slop callouts (5 PRs) | `submission_judge` (judge) + `pr_template_compliance` (mechanical) + `relevance` (judge) |
| Bucket A: never-started (10 issues) | `environment_works` (mechanical) + better failure surfacing |
| Bucket B: completed-without-PR (17 issues) | The state machine itself — no `completed` state without `submitted` |
| Puppeteer "Not working ×5" | `repro_evidence_present` (mechanical, structural) + `verified_evidence_present` (mechanical + visual diff) |
| markitdown unrelated cleanup | `relevance` (judge — one of two judge calls per issue) |
| vcpkg matplotlib (wrong language) | `eligibility` (mechanical) |
| opentofu already-assigned | `eligibility` (mechanical) |
| Repeated pyright#11308 dispatch | The state machine — issues have one workflow each, idempotent at the state level |
| uptime-kuma "AI-policy non-negotiable" | `eligibility` (mechanical CONTRIBUTING scan) + `pr_template_compliance` (mechanical) |

## Gate execution order

After every state transition, the orchestrator runs:
1. All `mechanical` gates registered for the new state, in declaration order.
   Any failure aborts immediately. **Mechanical gates run on every issue.**
2. All `judge` gates registered for the new state, sequentially (per the
   F1 semaphore). Defers go to the operator inbox. **Judge gates run at
   most twice per issue total: once after `fixed` (relevance) and once
   after `submittable` (submission_judge).**
3. All `human` gates registered for the new state. Always defer. (None
   currently registered — reserved for future high-stakes manual gates.)

A gate result is recorded to `gates.jsonl` regardless of outcome (pass /
fail / defer), so we can compute gate-level statistics in retro.

## Final gate count by kind

After the F1 rebalance:

| Kind | Count | Gates |
|---|---|---|
| mechanical | 9 | `eligibility`, `input_context_clean`, `environment_works`, `repro_evidence_present`, `diff_non_empty`, `verified_evidence_present`, `remediation_complete`, `no_upstream_refs`, `pr_template_compliance` |
| judge | 2 | `relevance` (after fixed), `submission_judge` (after submittable) |
| human | 0 | (reserved) |
