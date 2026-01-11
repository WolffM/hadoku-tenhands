# VibeDispatch Research: Agentic Workflow Orchestration Landscape

## Executive Summary

Your VibeDispatch vision is well-timed. The space has evolved significantly, and there are clear patterns emerging across successful projects. The key insight: **the projects that work best separate planning/research from execution**, and provide **human review gates** at strategic points. Your proposed pipeline (Objective → Plan → Tasks → Implementation → Review) aligns well with what's proving successful.

---

## Key Projects Analyzed

### 1. Open SWE (LangChain) - **Most Relevant**
**URL:** https://github.com/langchain-ai/open-swe

**Architecture:** Multi-agent with dedicated roles:
- **Manager**: Entry point, orchestrates state and routing
- **Planner**: Researches codebase, proposes detailed execution plan
- **Programmer**: Executes steps, writes code, runs tests
- **Reviewer**: Validates outputs, loops for fixes, opens PR

**Key Insights for VibeDispatch:**
- Uses GitHub labels (`open-swe`, `open-swe-auto`) to trigger workflows
- Human-in-the-loop: Plan review before execution (like your "review gate")
- "Double texting": Can accept new input while running
- Acknowledges limitation: Heavy planning/review cycle is overkill for small fixes
- Building separate CLI mode for lightweight tasks

**What to steal:**
- Label-based workflow triggering
- Separate planning agent that researches before acting
- Plan approval step before execution
- The acknowledgment that different task types need different pipelines (matches your workflow types idea)

---

### 2. SWE-agent (Princeton/Stanford) - **Benchmark Standard**
**URL:** https://github.com/SWE-agent/SWE-agent

**Architecture:**
- Single agent with unified "CodeAct" action space
- Uses bash + code execution as primary tools
- Configurable via single YAML file
- Sandboxed execution via Docker

**Key Insights:**
- Their "mini-swe-agent" (100 lines) achieves 74% on SWE-bench - proves simple can work
- Philosophy: "Put the LM in the middle, not the scaffold"
- Issue → Fix workflow, but no planning layer
- Good at single-issue fixes, not multi-step projects

**What to steal:**
- Benchmarking approach (track success rate by file span)
- Sandboxed execution pattern
- YAML-based configuration for flexibility

**What to avoid:**
- No planning step means it jumps straight to code
- Not designed for complex multi-part objectives

---

### 3. Sweep AI - **GitHub-Native Pattern**
**URL:** https://github.com/sweepai/sweep (now pivoted to JetBrains plugin)

**Architecture:**
- GitHub App that watches for labeled issues
- Vector DB for codebase understanding (embeddings + chunking)
- Generates PRs directly from issues

**Key Insights:**
- Label trigger pattern: Add "Sweep" label → bot picks up issue
- Heavy focus on code chunking and retrieval
- Self-recovery: Uses GitHub Actions to lint/test → tells Sweep → Sweep fixes → repeat
- Best for "small bugs and small features"

**What to steal:**
- GitHub Actions integration for validation loop
- Label-based trigger pattern
- Self-hosted Docker option

**What to avoid:**
- No explicit planning phase
- Works best on narrow tasks only

---

### 4. Chainlink - **Local-First Issue Tracker**
**URL:** https://github.com/dollspace-gay/chainlink

**Architecture:**
- SQLite-based local issue storage
- Session management with handoff notes (context preservation)
- Subissues, dependencies, milestones
- Claude Code hooks for behavioral guardrails

**Key Insights for VibeDispatch:**
- **Session handoff**: Preserves context across AI sessions
- **Customizable rules**: `.chainlink/rules/` for project-specific best practices
- **Context provider**: Can inject context into any AI agent
- **No GitHub sync**: Purely local, avoids merge complexity

**What to steal:**
- Session/handoff concept for preserving context
- Rules injection pattern
- Context provider abstraction (works with any agent)
- Local-first storage model

**What's missing (for your needs):**
- No planning/decomposition layer
- No agent routing (single agent assumed)
- No GitHub PR integration

---

### 5. BabyAGI - **Task Loop Pattern**
**URL:** https://github.com/yoheinakajima/babyagi

**Architecture:**
- Three-agent loop: Execution → Task Creation → Prioritization
- Vector DB for memory (stores task results)
- Continuous loop until objective complete

**Key Insights:**
- **Task creation from results**: New tasks generated based on completed task outcomes
- **Dynamic prioritization**: Reorders queue based on progress
- **Objective-driven**: Everything traces back to high-level goal

**What to steal:**
- The create-execute-prioritize loop pattern
- Using completed task results to inform next tasks
- Dynamic reprioritization based on progress

**What to avoid:**
- Can spiral into infinite loops
- High token consumption
- No human gates (runs until done or budget exhausted)

---

### 6. OpenHands (formerly OpenDevin) - **Platform Approach**
**URL:** https://github.com/All-Hands-AI/OpenHands

**Architecture:**
- Platform for building agents, not a single agent
- CodeAct framework: Unified code action space
- Supports multiple agent implementations
- "Micro agents" for specialized tasks

**Key Insights:**
- **Task decomposition**: Breaks complex tasks into steps, creates plans, adapts
- **Micro agents**: Specialized prompts for specific use cases (no coding required)
- **Sandbox execution**: Isolated Docker environments
- Benchmarked on SWE-bench, WebArena, etc.

**What to steal:**
- Micro-agent concept (specialized prompts per task type)
- Platform approach (pluggable agents)
- Sandbox isolation pattern

---

### 7. Aider - **Git-Native Pair Programming**
**URL:** https://github.com/Aider-AI/aider

**Architecture:**
- Terminal-based pair programming
- Repository map: Understands full codebase structure
- Tight git integration (auto-commits with messages)
- Multi-file editing in single changeset

**Key Insights:**
- **Repo map**: Creates map of entire codebase for context
- **File adding**: Only files "added to chat" can be edited
- **Auto-commit**: Every change committed with descriptive message
- **Architect mode**: Discuss before doing

**What to steal:**
- Repository map concept for context
- Explicit file scoping (only added files can be edited)
- Architect/discuss mode before code mode

---

## Pattern Synthesis: What Works

### 1. **Planning Before Execution**
Every successful system separates thinking from doing:
- Open SWE: Dedicated Planner agent
- GitHub Spec Kit: Spec → Plan → Tasks flow
- Aider: Architect mode before code mode

### 2. **Human Review Gates**
The winning pattern is strategic interruption:
- Open SWE: Plan approval before execution
- Your vision: Configurable gates per pipeline type

### 3. **Task Granularity Matters**
Your file-span heuristic is validated:
- SWE-bench success correlates with narrow scope
- Sweep: "small bugs and small features"
- Open SWE: Building CLI mode for small fixes

### 4. **GitHub as Persistence Layer**
Common pattern, but with caveats:
- Issues/PRs work well for tracking
- Labels for workflow triggering
- But some go local (Chainlink) to avoid sync complexity

### 5. **Context Bundling**
All successful systems manage context carefully:
- Aider: Repo map + explicit file adding
- Chainlink: Session handoff + context provider
- Open SWE: Planner "researches" before acting

---

## Gaps in Existing Tools (Your Opportunity)

| Gap | Your Vision Addresses It? |
|-----|---------------------------|
| No configurable pipeline types | ✅ Workflow Types (bug fix, design, linting, etc.) |
| No complexity-based routing | ✅ Task complexity heuristic |
| All-or-nothing human review | ✅ Configurable review gates |
| No objective → task decomposition | ✅ Plan → Tasks stage |
| Single agent assumption | ✅ Agent routing (Copilot, Claude Code, etc.) |
| No context bundling strategy | ✅ Tasks include all necessary context |

---

## Recommendations for VibeDispatch

### 1. **Start with Open SWE's Pattern**
Their Manager → Planner → Programmer → Reviewer flow maps closely to your Objective → Plan → Tasks → Implementation → Review. Study their implementation.

### 2. **Validate File-Span Heuristic**
Before building, run the analysis you proposed:
- Categorize past Copilot PRs by file span
- Measure success rate at each tier
- Define concrete thresholds

### 3. **Build Hybrid Storage**
Start GitHub-centric (issues + PRs), but:
- Keep local cache for fast operations
- Design abstraction layer for potential Chainlink-style local storage
- Use GitHub labels for workflow triggering

### 4. **Implement Pipeline Types Incrementally**
1. Start with simplest: Formatting/Linting (full auto)
2. Add: Bug Fix (plan review + auto implement)
3. Then: Design Enhancement (heavy early review)
4. Finally: Investigation pipeline (adds diagnosis stage)

### 5. **Steal Chainlink's Context Provider**
Their pattern of injecting context into any agent is elegant. Build something similar for your task bundling.

### 6. **Consider the "Spec Kit" Approach**
GitHub's new Spec Kit (spec → plan → tasks) is very close to your vision. Worth investigating as potential integration or inspiration.

---

## Research Questions: Preliminary Answers

### RQ1: Task Granularity Validation
- **Pattern observed**: 1-2 file changes succeed at high rates
- **Threshold**: 5+ files is "hard" across all tools
- **Validation needed**: Your specific Copilot data

### RQ2: Workflow Type Boundaries
Open SWE's acknowledgment that small fixes need different treatment validates your multi-pipeline approach. Context requirements vary significantly by type.

### RQ3: Context Bundling Strategy
- **Static analysis** (imports) + **embedding search** seems to be winning combo
- Island architecture limits scope naturally
- Auto-detection of relevant "island" is feasible

### RQ4: Chainlink Analysis
Answered above - key insights are session handoff, rules injection, and local-first storage. Missing planning/decomposition layer.

---

## Next Steps

1. **Deep dive into Open SWE source** - closest to your vision
2. **Build file-span analysis tool** for your existing Copilot PR data
3. **Prototype MVP** with single pipeline (bug fix or formatting)
4. **Design task schema** that works with GitHub issues
5. **Test Claude Code planning mode** with real objectives

---

*Research compiled: January 2026*