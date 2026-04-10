Inspect Copilot coding agent session logs. Requires `gh` CLI >= 2.80.0.

```bash
# List recent Copilot agent sessions (optionally filter by repo)
python3 scripts/copilot-sessions.py list --repo WolffM/hadoku-watchparty

# View full session log for a specific PR
python3 scripts/copilot-sessions.py log -R WolffM/hadoku-watchparty --pr 123

# View condensed thinking summary (strips file content noise)
python3 scripts/copilot-sessions.py summary -R WolffM/hadoku-watchparty --pr 123

# With TDD workflow analysis
python3 scripts/copilot-sessions.py summary -R WolffM/hadoku-watchparty --pr 123 --analyze

# Compare workflow compliance across multiple PRs
python3 scripts/copilot-sessions.py compare -R WolffM/hadoku-watchparty --prs 95,115,123

# Bulk thinking summaries
python3 scripts/copilot-sessions.py batch -R WolffM/hadoku-watchparty --prs 107,109,111
```

**How it works:** PR number → first commit SHA → copilot check-run → Actions run ID → job logs → `COPILOT_AGENT_SESSION_ID` → `gh agent-task view <id> --log`. Tool detection is pattern-based (no hardcoded tool names).

**Workflow analysis tracks:** reproduced, verified, tool_installed, code_review, codeql, self_corrected.

Run the command the user requests, substituting their repo and PR numbers. If `$ARGS` is empty, show this help text.
