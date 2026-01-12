# VibeDispatch Vision: Agentic Workflow Orchestration Platform

## Core Vision

VibeDispatch is an orchestration platform for agentic workflows. It manages discrete stages that tasks flow through:

```
Objective -> Plan -> Tasks -> Implementation -> Review
```

The platform:

- Routes work to the right agent for the right job (Copilot, Claude Code, Cursor, custom agents, or humans)
- Keeps things organized using GitHub issues and PRs as the persistence/tracking layer (may evolve to local management like Chainlink if needed)
- Provides rigid control over the process with configurable review gates at each stage
- Bundles tasks with all necessary context so agents don't need to fetch more

---

## Reference: Chainlink Project

See: https://github.com/dollspace-gay/chainlink

Chainlink does something similar - keeps objectives organized and flows them through stages. They handle issue management locally rather than in GitHub. We may adopt a similar approach if GitHub's data model proves limiting.

---

## The Pipeline Stages

### Stage 1: Objective

**Input**: High-level goal (from user's mind, .txt files, or future integrations)
**Output**: A well-defined objective with scope and success criteria

Example objectives:

- "Improve error handling in the auth module"
- "Investigate why /api/users returns 500 errors"
- "Add dark mode theme support"

### Stage 2: Plan

**Input**: Objective + codebase context
**Output**: A breakdown strategy - how the objective will be accomplished

The planning stage includes **research**:

- Searches relevant code files
- Finds past tasks/issues related to the objective
- Reads context files (agents.md, claude.md, etc.)
- Proposes an approach with specific file/function references

Claude Code's "planning mode" is already good at this - we leverage that capability.

**Review Gate**: For complex objectives, humans review the plan before task creation.

### Stage 3: Tasks

**Input**: Approved plan
**Output**: Small, atomic tasks that agents can accomplish reliably

**Key Heuristic**: Task complexity correlates with:

- **File span** - How many files need to change
- **Context breadth** - How much of the codebase needs to be understood

A task that touches 1-2 files with narrow context is easy. A task requiring understanding of 10+ files or cross-cutting concerns is hard and may need human-monitored execution.

Tasks are **specific**, not vague. Never "Refactor auth module" - instead "Add try/catch in auth.py:45 for the API call, return 401 on AuthError".

Each task includes:

- Clear, specific instructions
- All necessary context bundled in
- References to specific files/functions
- Expected outcome

### Stage 4: Implementation

**Input**: Task with bundled context
**Output**: PR with changes

Currently handled by GitHub Copilot via the existing "Assign Copilot" flow.

**Review Gate**: Depends on task complexity. Safe tasks (linting, formatting) can auto-proceed. Complex tasks need human review.

### Stage 5: Review

**Input**: PR ready for review
**Output**: Merged code or feedback

Currently handled by the existing "Review & Merge" flow.

---

## Task Complexity: Dynamic, Not Static

The core insight: **complexity is contextual and should be decided at runtime, not by static thresholds**.

Early designs considered hardcoded file-span thresholds (1-2 files = auto, 5+ = human), but this is too rigid. In practice:

- A 10-file formatting change might be trivial
- A 1-file security fix might need careful review
- Context matters more than metrics

**Our approach:**

- **All stages gated by default** - human reviews at each stage
- **"Yolo mode"** - at any gate, human can bypass remaining gates for this pipeline run
- **Agent recommendations** - planning/task agents can _suggest_ human involvement, but don't enforce it
- **Per-pipeline judgment** - each run is a contextual decision, not a formula

This keeps humans in control while allowing fast-tracking when appropriate. As we learn patterns, we may add _optional_ auto-advance rules, but never mandatory ones.

---

## Architecture Assumption: Octo-Astro Islands

The codebase follows an **octo-astro island architecture**:

- Main app with multiple child apps (islands)
- Child apps are isolated - changes in one don't affect others
- Each child app is small enough that full context is trivial

This architecture naturally limits context scope:

- Tasks within a child app only need that app's context
- Cross-island tasks are rare and flagged as complex
- "Shutting out" irrelevant context is structural, not algorithmic

---

## Workflow Types (Pipeline Configurations)

Different types of work need different review gates and context. Research needed to define exact boundaries.

### VibeCheck Pipeline (Current)

```
Objective -> Plan -> Tasks -> Implementation (manual) -> Review (manual)
```

- Automated security/quality scanning creates objectives
- Human reviews at implementation and review stages

### Bug Fix Pipeline

```
Objective -> Plan (review) -> Tasks -> Implementation -> Review (manual)
```

- Extra review at plan stage to verify the fix approach
- Implementation can be more automated once plan is approved
- **Context focus**: Error logs, stack traces, related code paths

### Design Enhancement Pipeline

```
Objective (review) -> Plan (review) -> Tasks -> Implementation (manual) -> Review (manual)
```

- Heavy review early in the process
- **Context focus**: Theme system locations, component usage patterns, design tokens

### Formatting/Linting Pipeline

```
Objective -> Plan -> Tasks -> Implementation (auto) -> Review (auto)
```

- Fully automated for safe, mechanical changes
- **Context focus**: Minimal - just the files to change

### Investigation Pipeline (e.g., 500 errors)

```
Objective -> Investigation -> Plan -> Tasks -> Implementation -> Review
```

- Adds an investigation stage that reviews logs, errors, traces
- Outputs a diagnosis before planning fixes
- **Context focus**: Logs, monitoring data, request traces

### Retrospective Pipeline

```
[Completed PRs] -> Analysis -> Objectives
```

- Runs on schedule or when changes accumulate (not continuously)
- Analyzes merged PRs for hotfixes, workflow failures, patterns
- Creates improvement objectives that feed back into other pipelines
- **Context focus**: PR history, CI/CD logs, issue linkage

---

## Research Questions

### RQ1: Gate Patterns in Practice

**Question**: What patterns emerge for when humans choose to "yolo" vs review carefully?

To investigate:

- Track which pipeline types tend to get yolo'd early
- Identify what context makes humans confident to fast-track
- Look for patterns that could inform _optional_ auto-advance suggestions

### RQ2: Workflow Type Boundaries

**Question**: What distinct workflow types do we need and what context does each require?

Categories to research:

- Bug fixes → logs, traces, error context
- Performance improvements → profiling data, hot paths
- Security improvements → vulnerability reports, security patterns
- New feature enhancements → architecture, API schemas
- Code transpilation/migration → source patterns, target patterns
- Design/UI changes → component tree, theme system
- Documentation → code structure, existing docs
- Testing improvements → coverage reports, test patterns
- Dependency updates → changelog, breaking changes

For each: What context is essential? What can be excluded?

### RQ3: Context Bundling Strategy

**Question**: How do we determine and package the right context for a task?

Given the island architecture:

- Can we auto-detect which "island" a task belongs to?
- What's the maximum context size that works well?
- How do we handle cross-island tasks?

Approaches to evaluate:

- Static analysis (imports, file references)
- Embedding similarity search
- Manual tagging per workflow type
- Hybrid approaches

### RQ4: Chainlink Analysis

**Question**: What can we learn from Chainlink's approach?

To investigate:

- How do they store objectives/plans/tasks locally?
- What's their data model?
- How do they handle the plan → task decomposition?
- What works well? What's painful?

---

## Constraints & Decisions

### GitHub-Centric (for now)

- GitHub issues and PRs provide good organization
- Easy to interface with via `gh` CLI
- Built-in notifications
- May evolve to local management (like Chainlink) if GitHub's model proves limiting

### Single Pipeline Per Repo (MVP)

- Avoids merge conflicts (primary concern)
- Simpler to reason about
- **Built async-ready** so we can expand to parallel pipelines later

### Human Review is OK to Block

- Pipelines can wait for human review indefinitely
- No timeout/auto-proceed needed
- Humans are available; blocking is acceptable

### Cross-Repo Context (Future)

- May need cross-repo context during objective/planning stages
- Multi-repo task creation may be needed
- Tasks split across repos need to be "linked" to share schema, conventions
- Architecture should be open to this but MVP stays single-repo

---

## Current Implementation (What Exists)

### Existing Stage 3: Assign Copilot

- Fetches vibeCheck-labeled issues
- Filters out already-assigned issues
- Recommends one issue per repo (highest severity)
- Skips repos with active Copilot PRs (except 'demo' labeled)
- User selects and assigns

**This becomes**: The "Implementation" stage, but fed by generated tasks instead of just GitHub issues.

### Existing Stage 4: Review & Merge

- Fetches open PRs
- Detects Copilot completion (no [WIP], completion comment)
- Separates "Ready for Review" vs "In Progress"
- Diff viewer, approve, merge actions

**This stays**: The "Review" stage, unchanged.

---

## Open Questions to Resolve

1. Should objectives be stored as GitHub issues with special labels, or locally (Chainlink-style)?
2. How does the plan stage present its output for human review?
3. What's the minimum viable task format that works for Copilot?
4. How do we handle task dependencies within a plan?
5. How do we track which objective spawned which tasks spawned which PRs?

---

## Research: Existing FOSS Projects

### Projects to Investigate

**Already Identified:**

- [Chainlink](https://github.com/dollspace-gay/chainlink) - Local objective/task management for agents

**To Discover** - Search GitHub and the web for projects in these categories:

### Search Terms by Problem Domain

**Agent Orchestration / Multi-Agent Systems:**

- "agent orchestration framework"
- "multi-agent coordination"
- "LLM agent workflow"
- "autonomous agent pipeline"
- "agent task queue"
- "agentic workflow engine"

**Task Decomposition / Planning:**

- "LLM task decomposition"
- "AI planning agent"
- "automatic task breakdown"
- "goal to task conversion"
- "hierarchical task network LLM"
- "plan and execute agent"

**Code Generation Orchestration:**

- "AI code generation pipeline"
- "automated PR generation"
- "code agent orchestrator"
- "software development agent"
- "coding assistant framework"
- "autonomous coding agent"

**Context Management / RAG for Code:**

- "code context retrieval"
- "codebase RAG"
- "repository context agent"
- "code-aware LLM"
- "semantic code search agent"

**GitHub/Issue Integration:**

- "GitHub automation agent"
- "issue to PR automation"
- "automated issue resolution"
- "GitHub Copilot orchestration"
- "issue triage agent"

**Human-in-the-Loop / Review Systems:**

- "human in the loop agent"
- "agent approval workflow"
- "supervised autonomous agent"
- "agent review system"

### Specific Projects/Tools to Research

These are known players in the space - check their GitHub repos and docs:

| Project                | What to Look For                             |
| ---------------------- | -------------------------------------------- |
| **AutoGPT**            | Task decomposition, agent loops, memory      |
| **BabyAGI**            | Task creation/prioritization patterns        |
| **GPT-Engineer**       | Code generation from specs, context handling |
| **Aider**              | Git integration, code context, PR workflows  |
| **SWE-agent**          | Issue-to-PR pipeline, benchmark data         |
| **OpenDevin**          | Agent architecture, task execution           |
| **Devon**              | Autonomous coding, planning approach         |
| **Mentat**             | Context selection, code understanding        |
| **Continue.dev**       | IDE integration, context management          |
| **Sweep**              | GitHub issue to PR automation                |
| **Cody (Sourcegraph)** | Code context retrieval at scale              |
| **Cursor**             | Agent mode implementation                    |
| **Claude Code**        | Planning mode, tool use patterns             |

### Research Questions for Each Project

When investigating a project, answer:

1. **Data Model**: How do they represent objectives/tasks/plans?
2. **Context Strategy**: How do they select relevant code context?
3. **Decomposition**: How do they break high-level goals into tasks?
4. **Execution**: How do they hand off tasks to agents?
5. **Tracking**: How do they track progress and lineage?
6. **Review Gates**: Do they support human review? How?
7. **Failure Handling**: What happens when an agent fails?
8. **Storage**: Local files? Database? GitHub? API?

### Output Format

For each researched project, create a brief in `docs/planning/research/`:

```
docs/planning/research/
├── chainlink.md
├── sweep.md
├── swe-agent.md
├── autogpt.md
└── ...
```

Each file should contain:

- Project URL
- One-paragraph summary
- Answers to the 8 research questions above
- Key insights relevant to VibeDispatch
- What we should steal/avoid

---

## Critical Assumptions to Validate

1. **All-gates-by-default is acceptable UX** - May need streamlining as volume grows
2. **Yolo mode provides enough control** - May need per-stage granularity
3. **Island architecture limits context** - True for our repos, may not generalize
4. **Claude Code planning mode works** - Need to test with real objectives
5. **GitHub can handle our data model** - May need local storage
6. **One pipeline per repo is sufficient throughput** - Monitor and adjust
