#!/usr/bin/env python3
"""Copilot Agent Session Inspector.

Fetches and analyzes Copilot coding agent session logs from GitHub.
Requires: gh CLI >= 2.80.0 (with agent-task support)

Usage:
    # List all sessions
    python scripts/copilot-sessions.py list

    # List sessions for a specific repo
    python scripts/copilot-sessions.py list --repo owner/repo-name

    # View full session log for a PR
    python scripts/copilot-sessions.py log --repo owner/repo-name --pr 123

    # View thinking summary only (strips file content noise)
    python scripts/copilot-sessions.py summary --repo owner/repo-name --pr 123

    # Compare sessions across multiple PRs
    python scripts/copilot-sessions.py compare --repo owner/repo-name --prs 95,115,123

    # Bulk summary for a range of PRs
    python scripts/copilot-sessions.py batch --repo owner/repo-name --prs 107,109,111
"""

import argparse
import io
import json
import re
import subprocess
import sys

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def run_gh(args, timeout=30):
    """Run a gh CLI command. Returns (stdout, ok)."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return result.stdout.strip(), result.returncode == 0
    except subprocess.TimeoutExpired:
        return "", False
    except FileNotFoundError:
        print("Error: gh CLI not found. Install from https://cli.github.com/", file=sys.stderr)
        sys.exit(1)


def get_session_id(repo, pr_number):
    """Get the Copilot agent session ID for a PR by inspecting its Actions job logs."""
    # Get the first commit SHA (the "Initial plan" commit from copilot)
    commits_json, ok = run_gh([
        "api", f"repos/{repo}/pulls/{pr_number}/commits", "--jq", ".[0].sha"
    ])
    if not ok or not commits_json:
        return None

    first_sha = commits_json.strip()

    # Find the copilot check run's Actions run ID
    check_json, ok = run_gh([
        "api", f"repos/{repo}/commits/{first_sha}/check-runs",
        "--jq", '.check_runs[] | select(.name == "copilot") | .details_url'
    ])
    if not ok or not check_json:
        return None

    run_match = re.search(r"runs/(\d+)", check_json)
    if not run_match:
        return None
    run_id = run_match.group(1)

    # Get the job ID
    job_id, ok = run_gh([
        "api", f"repos/{repo}/actions/runs/{run_id}/jobs", "--jq", ".jobs[0].id"
    ])
    if not ok or not job_id:
        return None

    # Fetch job logs and extract session ID
    logs, ok = run_gh([
        "api", f"repos/{repo}/actions/jobs/{job_id}/logs"
    ], timeout=60)
    if not ok:
        return None

    session_match = re.search(r"COPILOT_AGENT_SESSION_ID: ([a-f0-9-]+)", logs)
    if session_match:
        return session_match.group(1)
    return None


def get_session_log(session_id):
    """Fetch the full session log for a Copilot agent session."""
    log, ok = run_gh(["agent-task", "view", session_id, "--log"], timeout=120)
    if ok:
        return log
    return None


def extract_thinking(log_text):
    """Extract the agent's thinking/actions from a session log.

    Filters out indented file content and keeps:
    - Agent reasoning (unindented text)
    - Tool calls (Bash:, Call to, View, Create:)
    - Progress updates
    - Bash command lines and their key output
    """
    lines = log_text.split("\n")
    result = []
    in_bash_output = False
    bash_output_lines = 0

    for line in lines:
        stripped = line.rstrip()

        # Skip empty lines
        if not stripped:
            if result and result[-1] != "":
                result.append("")
            continue

        # Always include these markers
        if any(stripped.startswith(p) for p in [
            "Start ", "View ", "Bash:", "Call to ", "Progress update:",
            "Run ", "Create:", "$ ",
        ]):
            result.append(stripped)
            if stripped.startswith("Bash:") or stripped.startswith("$ "):
                in_bash_output = True
                bash_output_lines = 0
            continue

        # Track bash output (show first few lines)
        if in_bash_output:
            bash_output_lines += 1
            if bash_output_lines <= 5:
                result.append(f"  {stripped}")
            elif bash_output_lines == 6:
                result.append("  ...")
            if stripped.startswith("<exited"):
                in_bash_output = False
            continue

        # Agent thinking: lines that don't start with heavy indentation
        if not stripped.startswith("  ") and not stripped.startswith("\t"):
            # Skip lines that look like file content (code patterns)
            if any(stripped.startswith(p) for p in [
                "│", "|", "def ", "class ", "import ", "from ", "const ",
                "function ", "export ", "return ", "if ", "for ", "while ",
                "try:", "except", "else:", "elif ", "async ", "await ",
                "{", "}", "//", "/*", "<!--", "```",
            ]):
                continue
            result.append(stripped)

    return "\n".join(result)


def _extract_bash_commands(log_text):
    """Extract all bash commands from the session log as (command_str, line_index) tuples."""
    commands = []
    lines = log_text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped.startswith("$ "):
            commands.append((stripped[2:].strip(), i))
    return commands


def _classify_command(cmd, description=""):
    """Classify a bash command into categories.

    Uses the command itself plus the optional Bash: description line for context.
    Detection is dynamic — no hardcoded tool names. Instead, it recognizes
    structural patterns: npx/pipx invocations, "check"/"lint"/"scan" verbs,
    install commands, test runners, and build tools.

    Returns a dict with:
    - is_install: package/tool installation command
    - is_test: test runner invocation
    - is_lint: linter/checker/scanner invocation
    - is_build: build/compile/typecheck command
    - tool_name: best-guess tool name extracted from the command, or None
    """
    cmd_lower = cmd.lower()
    desc_lower = description.lower()
    result = {
        "is_install": False,
        "is_test": False,
        "is_lint": False,
        "is_build": False,
        "tool_name": None,
    }

    # --- Install detection ---
    install_match = re.search(
        r"\b(npm install|pip3? install|apt-get install|brew install|"
        r"cargo install|gem install|go install)\s+(?:-\w+\s+)*(\S+)",
        cmd_lower,
    )
    if install_match:
        result["is_install"] = True
        result["tool_name"] = install_match.group(2).split("@")[0].split("/")[-1]
        return result

    # --- Test detection ---
    test_match = re.search(
        r"\b(pytest|npm test|pnpm test|jest|mocha|vitest|cargo test|go test)\b",
        cmd_lower,
    )
    if test_match:
        result["is_test"] = True
        result["tool_name"] = test_match.group(1)
        return result

    # --- Build/typecheck detection ---
    build_match = re.search(
        r"\b(tsc|npm run build|pnpm build|pnpm typecheck|"
        r"cargo build|make\b|gcc\b|g\+\+)",
        cmd_lower,
    )
    if build_match:
        result["is_build"] = True
        result["tool_name"] = build_match.group(1)
        return result

    # --- Lint/check/scan detection ---
    # These are the common shell commands and args we never want to report as tools
    noise = frozenset({
        # Shell builtins and common commands
        "cd", "ls", "cat", "head", "tail", "echo", "find", "grep", "rg",
        "git", "which", "npm", "pip", "pip3", "node", "python", "python3",
        "bash", "sh", "true", "false", "sed", "awk", "curl", "wget",
        "mkdir", "rm", "cp", "mv", "chmod", "chown", "touch", "wc",
        "sort", "uniq", "tr", "cut", "diff", "patch", "tar", "gzip",
        "yes", "--yes", "--", "sudo", "env", "xargs", "tee", "read",
        # Package managers (bare invocations, not "pnpm test" etc.)
        "pnpm", "yarn", "bun", "npx", "pipx", "cargo", "gem", "go",
        "apt-get", "brew", "dnf", "yum", "pacman",
    })

    def _is_filename(name):
        """Check if something looks like a filename rather than a tool."""
        return "." in name and name.rsplit(".", 1)[-1] in (
            "py", "js", "ts", "mjs", "cjs", "jsx", "tsx", "json", "yaml",
            "yml", "md", "txt", "toml", "cfg", "ini", "xml", "html", "css",
            "sh", "bash", "zsh", "rb", "rs", "go", "java", "c", "h", "cpp",
        )

    def _clean_tool(name):
        """Normalize a tool name: strip -cli suffix, path prefixes, @version."""
        name = name.split("@")[0].split("/")[-1]
        if name.endswith("-cli"):
            name = name[:-4]
        return name

    # 1. npx <tool> or pipx run <tool>: the next arg is the tool
    npx_match = re.search(r"\b(?:npx|pipx run)\s+(?:--\s+)?(?:--yes\s+)?(\S+)", cmd_lower)
    if npx_match:
        tool = _clean_tool(npx_match.group(1))
        if tool not in noise and not _is_filename(tool):
            result["is_lint"] = True
            result["tool_name"] = tool
            return result

    # 2. <tool> check|lint|scan|analyze — verb pattern
    verb_match = re.search(r"\b(\S+)\s+(?:check|lint|scan|analyze)\b", cmd_lower)
    if verb_match:
        tool = _clean_tool(verb_match.group(1))
        if tool not in noise and not _is_filename(tool):
            result["is_lint"] = True
            result["tool_name"] = tool
            return result

    # 3. Description-based: if the Bash: line mentions "run X", "verify", "check"
    #    and the command invokes something non-trivial, use the description to
    #    extract the tool name
    desc_tool_match = re.search(
        r"\b(?:run|verify|check|re-?run|confirm)\s+(\S+)", desc_lower,
    )
    if desc_tool_match:
        candidate = _clean_tool(desc_tool_match.group(1))
        # Verify it also appears in the actual command
        if candidate not in noise and not _is_filename(candidate) and candidate in cmd_lower:
            result["is_lint"] = True
            result["tool_name"] = candidate
            return result

    # 4. Direct invocation: the command starts with (or pipes into) a tool
    #    like "markdownlint file.md" or "bandit -r ."
    #    We look for the first "real" token after cd and path changes
    #    that has a flag or file argument following it
    direct_match = re.search(
        r"(?:^|&&\s*|;\s*)"          # start of command or chained
        r"(?:cd\s+\S+\s*&&\s*)?"     # optional cd prefix
        r"(\b[a-z][\w-]*\b)"         # candidate tool name
        r"\s+"                        # followed by space
        r"(?:-|[/.\w])",             # then a flag or file path
        cmd_lower,
    )
    if direct_match:
        candidate = _clean_tool(direct_match.group(1))
        if candidate not in noise and not _is_filename(candidate) and len(candidate) > 2:
            # Extra validation: check the description mentions this tool,
            # OR the command has typical lint-tool flags
            has_lint_flags = bool(re.search(
                r"\s(?:-r\b|--select|--fix|--config|--rule|--format|--output)",
                cmd_lower,
            ))
            mentioned_in_desc = candidate in desc_lower
            if has_lint_flags or mentioned_in_desc:
                result["is_lint"] = True
                result["tool_name"] = candidate
                return result

    return result


def analyze_workflow(log_text):
    """Analyze a session log for TDD workflow compliance.

    Dynamically detects tools from bash commands rather than using a hardcoded
    list. Tracks what ran before vs after the first file edit to determine
    reproduce/verify behavior.

    Returns a dict with:
    - reproduced: Did the agent run a lint/check tool before editing?
    - verified: Did the agent re-run a lint/check tool after editing?
    - tool_installed: Did the agent install a tool?
    - code_review: Did the agent run code review?
    - codeql: Did the agent run CodeQL?
    - self_corrected: Did the agent edit files after code review?
    - tools_used: List of tools detected in bash commands
    - steps: Ordered list of workflow steps
    """
    steps = []
    tools_used = set()
    lint_runs_before_edit = []
    lint_runs_after_edit = []
    first_edit_seen = False
    installed_tools = set()

    # Track the most recent Bash: description to pass as context
    last_bash_desc = ""

    lines = log_text.split("\n")
    for line in lines:
        stripped = line.rstrip()

        if stripped.startswith("View "):
            if "View " not in [s.split(":")[0] for s in steps[-3:]] if steps else True:
                steps.append(f"View: {stripped[5:]}")

        elif stripped.startswith("Bash:"):
            cmd_desc = stripped[5:].strip()
            steps.append(f"Bash: {cmd_desc}")
            last_bash_desc = cmd_desc

        elif stripped.startswith("$ "):
            raw_cmd = stripped[2:].strip()
            classification = _classify_command(raw_cmd, description=last_bash_desc)
            tool = classification["tool_name"]

            if classification["is_install"]:
                if tool:
                    installed_tools.add(tool)
                    tools_used.add(tool)

            elif classification["is_lint"]:
                if tool:
                    tools_used.add(tool)
                    if not first_edit_seen:
                        lint_runs_before_edit.append(tool)
                    else:
                        lint_runs_after_edit.append(tool)

            elif classification["is_test"]:
                if tool:
                    tools_used.add(tool)
                steps.append(f"Test: {tool or raw_cmd[:40]}")

            elif classification["is_build"]:
                if tool:
                    tools_used.add(tool)
                steps.append(f"Build: {tool or raw_cmd[:40]}")

        elif stripped.startswith("Call to edit") or stripped.startswith("Call to write"):
            if not first_edit_seen:
                first_edit_seen = True
                steps.append("--- FIRST EDIT ---")
            steps.append("Edit")

        elif stripped.startswith("Create:"):
            if not first_edit_seen:
                first_edit_seen = True
                steps.append("--- FIRST EDIT ---")
            steps.append(f"Create: {stripped[7:].strip()}")

        elif stripped.startswith("Call to code_review"):
            steps.append("Code Review")

        elif stripped.startswith("Run CodeQL"):
            steps.append("CodeQL")

        elif stripped.startswith("Progress update:"):
            steps.append(f"Progress: {stripped[16:].strip()[:60]}")

    reproduced = len(lint_runs_before_edit) > 0
    verified = len(lint_runs_after_edit) > 0
    tool_installed = len(installed_tools) > 0
    code_review = any("Code Review" in s for s in steps)
    codeql = any("CodeQL" in s for s in steps)

    # Self-correction: edits after code review
    review_idx = None
    edit_after_review = False
    for i, s in enumerate(steps):
        if s == "Code Review":
            review_idx = i
        if review_idx is not None and i > review_idx and s in ("Edit", "Create"):
            edit_after_review = True

    return {
        "reproduced": reproduced,
        "verified": verified,
        "tool_installed": tool_installed,
        "code_review": code_review,
        "codeql": codeql,
        "self_corrected": edit_after_review,
        "tools_used": sorted(tools_used),
        "installed_tools": sorted(installed_tools),
        "lint_runs_before_edit": lint_runs_before_edit,
        "lint_runs_after_edit": lint_runs_after_edit,
        "step_count": len(steps),
        "steps": steps,
    }


def check_gh_version():
    """Verify gh CLI is >= 2.80.0 (required for agent-task commands)."""
    out, ok = run_gh(["--version"])
    if not ok:
        print("Error: could not determine gh version", file=sys.stderr)
        sys.exit(1)
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    if not match:
        print(f"Error: could not parse gh version from: {out}", file=sys.stderr)
        sys.exit(1)
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if (major, minor) < (2, 80):
        print(f"Error: gh {major}.{minor}.{patch} is too old. "
              f"Need >= 2.80.0 for agent-task support. "
              f"Upgrade: sudo apt-get update && sudo apt-get install gh", file=sys.stderr)
        sys.exit(1)
    return f"{major}.{minor}.{patch}"


def cmd_list(args):
    """List Copilot agent sessions.

    NOTE: gh agent-task list does not support -R (repo filter).
    Filtering is done client-side after fetching all tasks.
    Requires OAuth token (gh auth login), not PAT.
    """
    check_gh_version()
    gh_args = ["agent-task", "list"]
    if args.limit:
        gh_args += ["-L", str(args.limit)]
    output, ok = run_gh(gh_args)
    if ok:
        # Filter by repo if specified (client-side since API doesn't support it)
        if args.repo:
            lines = [l for l in output.split("\n") if args.repo in l]
            print("\n".join(lines))
        else:
            print(output)
    else:
        if "OAuth" in output or "Re-authenticate" in output:
            print("Error: gh agent-task requires OAuth token. Run: gh auth login",
                  file=sys.stderr)
        else:
            print(f"Failed to list sessions: {output}", file=sys.stderr)


def cmd_log(args):
    """View full session log for a PR."""
    session_id = get_session_id(args.repo, args.pr)
    if not session_id:
        print(f"Could not find session ID for PR #{args.pr}", file=sys.stderr)
        sys.exit(1)

    print(f"Session: {session_id}", file=sys.stderr)
    log = get_session_log(session_id)
    if log:
        print(log)
    else:
        print("Failed to fetch session log", file=sys.stderr)


def cmd_summary(args):
    """View thinking summary for a PR."""
    session_id = get_session_id(args.repo, args.pr)
    if not session_id:
        print(f"Could not find session ID for PR #{args.pr}", file=sys.stderr)
        sys.exit(1)

    print(f"Session: {session_id}", file=sys.stderr)
    log = get_session_log(session_id)
    if not log:
        print("Failed to fetch session log", file=sys.stderr)
        sys.exit(1)

    thinking = extract_thinking(log)
    print(thinking)

    if args.analyze:
        print("\n" + "=" * 60)
        analysis = analyze_workflow(log)
        print(f"Reproduced before fix: {'YES' if analysis['reproduced'] else 'NO'}")
        print(f"Verified after fix:    {'YES' if analysis['verified'] else 'NO'}")
        print(f"Installed tools:       {'YES' if analysis['tool_installed'] else 'NO'}")
        print(f"Code review:           {'YES' if analysis['code_review'] else 'NO'}")
        print(f"CodeQL scan:           {'YES' if analysis['codeql'] else 'NO'}")
        print(f"Self-corrected:        {'YES' if analysis['self_corrected'] else 'NO'}")
        print(f"Tools used:            {', '.join(analysis['tools_used']) or 'none'}")
        print(f"Total steps:           {analysis['step_count']}")


def cmd_compare(args):
    """Compare workflow across multiple PRs."""
    prs = [int(p.strip()) for p in args.prs.split(",")]

    results = []
    for pr_num in prs:
        print(f"Fetching PR #{pr_num}...", file=sys.stderr)
        session_id = get_session_id(args.repo, pr_num)
        if not session_id:
            print(f"  Could not find session for PR #{pr_num}", file=sys.stderr)
            results.append({"pr": pr_num, "error": "no session found"})
            continue

        log = get_session_log(session_id)
        if not log:
            print(f"  Could not fetch log for PR #{pr_num}", file=sys.stderr)
            results.append({"pr": pr_num, "error": "log fetch failed"})
            continue

        analysis = analyze_workflow(log)
        analysis["pr"] = pr_num
        analysis["session_id"] = session_id
        results.append(analysis)

    # Print comparison table
    print()
    print(f"{'PR':<6} {'Repro':<7} {'Verify':<8} {'Install':<9} {'Review':<8} {'CodeQL':<8} {'Self-Fix':<10} {'Steps':<7} {'Tools'}")
    print("-" * 100)

    for r in results:
        if "error" in r:
            print(f"#{r['pr']:<5} {r['error']}")
            continue

        yn = lambda v: "YES" if v else "no"
        print(
            f"#{r['pr']:<5} "
            f"{yn(r['reproduced']):<7} "
            f"{yn(r['verified']):<8} "
            f"{yn(r['tool_installed']):<9} "
            f"{yn(r['code_review']):<8} "
            f"{yn(r['codeql']):<8} "
            f"{yn(r['self_corrected']):<10} "
            f"{r['step_count']:<7} "
            f"{', '.join(r['tools_used'])}"
        )

    if args.json:
        # Strip non-serializable data for clean JSON
        for r in results:
            r.pop("steps", None)
        print("\n" + json.dumps(results, indent=2))


def cmd_batch(args):
    """Bulk summary for multiple PRs."""
    prs = [int(p.strip()) for p in args.prs.split(",")]

    for pr_num in prs:
        print(f"\n{'=' * 70}")
        print(f"PR #{pr_num}")
        print(f"{'=' * 70}")

        session_id = get_session_id(args.repo, pr_num)
        if not session_id:
            print(f"Could not find session for PR #{pr_num}")
            continue

        log = get_session_log(session_id)
        if not log:
            print(f"Could not fetch log for PR #{pr_num}")
            continue

        thinking = extract_thinking(log)
        # Show condensed version
        lines = thinking.split("\n")
        if len(lines) > 40:
            for line in lines[:20]:
                print(line)
            print(f"\n  ... ({len(lines) - 40} lines omitted) ...\n")
            for line in lines[-20:]:
                print(line)
        else:
            print(thinking)

        analysis = analyze_workflow(log)
        print(f"\n  Reproduced: {'YES' if analysis['reproduced'] else 'NO'} | "
              f"Verified: {'YES' if analysis['verified'] else 'NO'} | "
              f"CodeQL: {'YES' if analysis['codeql'] else 'NO'} | "
              f"Self-fix: {'YES' if analysis['self_corrected'] else 'NO'} | "
              f"Tools: {', '.join(analysis['tools_used']) or 'none'}")


def main():
    parser = argparse.ArgumentParser(
        description="Copilot Agent Session Inspector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = sub.add_parser("list", help="List agent sessions")
    p_list.add_argument("--repo", help="Filter by repo (owner/repo)")
    p_list.add_argument("--limit", "-L", type=int, default=30, help="Max sessions to fetch")

    # log
    p_log = sub.add_parser("log", help="View full session log for a PR")
    p_log.add_argument("--repo", "-R", required=True, help="Repository (owner/repo)")
    p_log.add_argument("--pr", type=int, required=True, help="PR number")

    # summary
    p_summary = sub.add_parser("summary", help="View thinking summary for a PR")
    p_summary.add_argument("--repo", "-R", required=True, help="Repository (owner/repo)")
    p_summary.add_argument("--pr", type=int, required=True, help="PR number")
    p_summary.add_argument("--analyze", "-a", action="store_true", help="Include workflow analysis")

    # compare
    p_compare = sub.add_parser("compare", help="Compare workflow across PRs")
    p_compare.add_argument("--repo", "-R", required=True, help="Repository (owner/repo)")
    p_compare.add_argument("--prs", required=True, help="Comma-separated PR numbers")
    p_compare.add_argument("--json", action="store_true", help="Also output JSON")

    # batch
    p_batch = sub.add_parser("batch", help="Bulk summary for multiple PRs")
    p_batch.add_argument("--repo", "-R", required=True, help="Repository (owner/repo)")
    p_batch.add_argument("--prs", required=True, help="Comma-separated PR numbers")

    args = parser.parse_args()

    commands = {
        "list": cmd_list,
        "log": cmd_log,
        "summary": cmd_summary,
        "compare": cmd_compare,
        "batch": cmd_batch,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
