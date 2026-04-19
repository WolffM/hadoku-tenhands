# Phase 4 targets — attempt #2

Fresh picks selected 2026-04-19 to exercise different surfaces than
attempt #1. Attempt #1 (phase4-external-20260419-0535) produced 10/10
WorkflowExecutionFailed — 4 on aggregator aged-out issue-brief, 6 on
`has_issues=false` on the fork.

Attempt #2 dispatches after the following fixes landed:
- `_configure_fork_safety` now PATCHes `has_issues=true` before Actions config
- Fork whitelist tightened to `dynamic/copilot-swe-agent/copilot` only
- Eligibility fallback: scored-issues → `gh api` → `POST /compose-brief`
- `IssueWorkflow` catches generic `Exception` → clean `aborted` instead of `WorkflowExecutionFailed`

## Diversification goals (vs attempt #1)

Attempt #1 was heavy JS/TS. Attempt #2 intentionally spans:
- Language: **C++, Rust, Go, Python, TS/JS** (was: only JS/TS/Go)
- Stack surface: Kubernetes controller, package manager, LLM runtime, ASGI framework, frontend framework, Windows native CLI
- Difficulty: 2 beginner, 5 intermediate, 3 advanced

## The 10

| # | Upstream | Issue | Lang | Diff | 👍 | 💬 | Title |
|---|---|---|---|---|---|---|---|
| 1 | vuejs/core | #12575 | TS | intermediate | 0 | 34 | Vue not catching errors on server side in SSR when using... |
| 2 | pnpm/pnpm | #2008 | TS | beginner | 50 | 28 | Request: preserve comments and key orders in package.yaml |
| 3 | microsoft/winget-cli | #2686 | C++ | advanced | 21 | 52 | "No installed package found matching input criteria." |
| 4 | expressjs/express | #2281 | JS | intermediate | 14 | 32 | '/' route breaks strict routing |
| 5 | ollama/ollama | #15315 | Go | intermediate | 7 | 45 | gemma4:e4b with ollama 0.20.1 still has tool parsing errors |
| 6 | apache/airflow | #36090 | Python | intermediate | 4 | 45 | Deferrable operator tasks do not call `on_kill` |
| 7 | ggerganov/llama.cpp | #17284 | C/C++ | beginner | 3 | 45 | Eval bug: Server Fails with HTTP 400 (Context Size Exceeded) |
| 8 | argoproj/argo-cd | #20828 | Go | intermediate | 16 | 17 | If any conversion webhook on any CRD isn't available... |
| 9 | biomejs/biome | #6376 | Rust | advanced | 14 | 6 | Plugins are not working inside subprojects |
| 10 | tiangolo/fastapi | #10180 | Python | intermediate | 9 | 17 | Mounting sub-applications under `APIRouter` |

## Exclusions applied

- **Jade-hare era (34 repos)** — historical fork parents
- **Attempt #1 (10 repos)** — don't retest same surface
- **Known blockers** — microsoft/TypeScript (winding down), oven-sh/bun (slug hyphen)
- **Lint-class titles** — vibeCheck/markdownlint/bandit/etc auto-generated findings
- **Bad labels** — awaiting-details, external-issue, internal-fix, wontfix, duplicate, needs-triage, stale

## Surfaces we're hoping to exercise

Fresh problems we might uncover:

| Surface | Target driving it |
|---|---|
| Windows-native build env (VS / MSBuild) | winget-cli |
| Rust toolchain setup | biome |
| C/C++ make build | llama.cpp |
| Python ASGI + plugin architecture | fastapi |
| Kubernetes controller code shape | argo-cd |
| Go binary + HTTP server | ollama |
| Hyphenated slug that doesn't collide (shadcn-ui also had this but it aged out) | — (none this batch) |
| DCO-required repos | airflow (Apache CLA territory) |
| Very old issue (9 years) | express #2281 (filed 2014) |

## Exclusion list carryover

Same as attempt #1 plus the 10 from that attempt.
