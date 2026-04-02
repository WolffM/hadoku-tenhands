"""
Workflow Templates — tool-specific static analysis workflow builders.

Generates GitHub Actions workflow YAML for the static-analysis.yml
dispatched during Stage 4b. Each builder produces a job dict that gets
assembled into a complete workflow.

When a toolchain profile is available from the aggregator, the workflow
matches the upstream repo's actual linters. Without a profile, it falls
back to sensible language defaults.
"""

try:
    from ..config import GITHUB_ACTIONS_BOT_NAME, GITHUB_ACTIONS_BOT_EMAIL
except ImportError:
    from config import GITHUB_ACTIONS_BOT_NAME, GITHUB_ACTIONS_BOT_EMAIL

CHECKSTYLE_VERSION = "10.21.4"

_LFS_CHECKOUT = (
    "- uses: actions/checkout@v4\n"
    "  with:\n"
    "    ref: ${{ inputs.ref }}\n"
    "  env:\n"
    "    GIT_LFS_SKIP_SMUDGE: '1'"
)


def _COMMIT_FIXES_STEP(message):
    """Build a git commit+push step for auto-fixed changes."""
    return (
        "- name: Commit fixes\n"
        "  run: |\n"
        f"    git config user.name '{GITHUB_ACTIONS_BOT_NAME}'\n"
        f"    git config user.email '{GITHUB_ACTIONS_BOT_EMAIL}'\n"
        "    git add -A\n"
        f"    git diff --cached --quiet || git commit -m '{message}'\n"
        "    git push || true"
    )


def build_ruff_job():
    """Ruff linter job (Python)."""
    return {
        "name": "ruff",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-python@v5\n  with:\n    python-version: '3.x'",
            "- run: pip install ruff",
            "- name: Auto-fix\n  run: ruff check . --fix || true",
            _COMMIT_FIXES_STEP("style: auto-fix ruff findings"),
            "- run: ruff check . --output-format=github",
        ],
    }


def build_eslint_job():
    """ESLint job (JavaScript/TypeScript)."""
    return {
        "name": "eslint",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-node@v4\n  with:\n    node-version: '20'",
            "- name: Install dependencies\n  run: |\n"
            "    if [ -f yarn.lock ]; then corepack enable && yarn install --immutable || yarn install\n"
            "    elif [ -f pnpm-lock.yaml ]; then corepack enable && pnpm install --frozen-lockfile || pnpm install\n"
            "    elif [ -f package-lock.json ]; then npm ci\n"
            "    else npm install\n"
            "    fi",
            "- name: Auto-fix\n  run: npx eslint . --fix || true",
            _COMMIT_FIXES_STEP("style: auto-fix eslint findings"),
            "- run: npx eslint . || true",
        ],
    }


def build_biome_job():
    """Biome linter/formatter job (JavaScript/TypeScript)."""
    return {
        "name": "biome",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-node@v4\n  with:\n    node-version: '20'",
            "- name: Auto-fix\n  run: npx @biomejs/biome check . --write || true",
            _COMMIT_FIXES_STEP("style: auto-fix biome findings"),
            "- run: npx @biomejs/biome check .",
        ],
    }


def build_golangci_lint_job():
    """golangci-lint job (Go)."""
    return {
        "name": "golangci-lint",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-go@v5\n  with:\n    go-version: 'stable'",
            "- run: go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest",
            "- name: Auto-fix\n  run: golangci-lint run --fix || true",
            _COMMIT_FIXES_STEP("style: auto-fix golangci-lint findings"),
            "- run: golangci-lint run",
        ],
    }


def build_go_vet_job():
    """go vet job (Go fallback)."""
    return {
        "name": "go-vet",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-go@v5\n  with:\n    go-version: 'stable'",
            "- run: go vet ./...",
            "- run: go test ./... || true",
        ],
    }


def build_clippy_job():
    """Clippy job (Rust)."""
    return {
        "name": "clippy",
        "steps": [
            _LFS_CHECKOUT,
            "- run: rustup component add clippy",
            "- name: Auto-fix\n  run: cargo clippy --fix --allow-dirty || true",
            _COMMIT_FIXES_STEP("style: auto-fix clippy findings"),
            "- run: cargo clippy -- -D warnings",
        ],
    }


def build_codeql_job(language):
    """CodeQL security analysis job."""
    lang = (language or "").lower()
    # Map to CodeQL language identifiers
    codeql_lang_map = {
        "python": "python",
        "javascript": "javascript-typescript",
        "typescript": "javascript-typescript",
        "go": "go",
        "java": "java-kotlin",
        "rust": "rust",
        "ruby": "ruby",
        "c": "c-cpp",
        "c++": "c-cpp",
        "cpp": "c-cpp",
        "c#": "csharp",
        "csharp": "csharp",
        "kotlin": "java-kotlin",
    }
    codeql_lang = codeql_lang_map.get(lang, "python")

    return {
        "name": "codeql",
        "steps": [
            _LFS_CHECKOUT,
            f"- uses: github/codeql-action/init@v3\n  with:\n    languages: {codeql_lang}",
            "- uses: github/codeql-action/analyze@v3",
        ],
    }


def build_pytest_job():
    """Pytest job (Python test runner)."""
    return {
        "name": "pytest",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-python@v5\n  with:\n    python-version: '3.x'",
            "- run: pip install -r requirements.txt 2>/dev/null || true",
            "- run: pip install pytest 2>/dev/null || true",
            "- run: python -m pytest -v || true",
        ],
    }


def build_cppcheck_job():
    """cppcheck job (C/C++)."""
    return {
        "name": "cppcheck",
        "steps": [
            _LFS_CHECKOUT,
            "- name: Install cppcheck\n  run: sudo apt-get update && sudo apt-get install -y cppcheck",
            "- run: cppcheck --enable=warning,style,performance --error-exitcode=1 --inline-suppr --template='{file}:{line}: {severity}: {message} [{id}]' . 2>&1 || true",
        ],
    }


def build_dotnet_format_job():
    """dotnet format job (C#)."""
    return {
        "name": "dotnet-format",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-dotnet@v4\n  with:\n    dotnet-version: '8.x'",
            "- name: Auto-fix\n  run: dotnet format --verify-no-changes || dotnet format",
            _COMMIT_FIXES_STEP("style: auto-fix dotnet format findings"),
            "- run: dotnet format --verify-no-changes || true",
        ],
    }


def build_checkstyle_job():
    """Checkstyle job (Java)."""
    return {
        "name": "checkstyle",
        "steps": [
            _LFS_CHECKOUT,
            "- uses: actions/setup-java@v4\n  with:\n    distribution: 'temurin'\n    java-version: '21'",
            "- name: Run checkstyle\n  run: |\n"
            f"    curl -sLO https://github.com/checkstyle/checkstyle/releases/download/checkstyle-{CHECKSTYLE_VERSION}/checkstyle-{CHECKSTYLE_VERSION}-all.jar\n"
            "    java -jar checkstyle-*.jar -c /google_checks.xml src/ || true",
        ],
    }


# ============ Tool Registry ============

TOOL_BUILDERS = {
    "ruff": build_ruff_job,
    "eslint": build_eslint_job,
    "biome": build_biome_job,
    "golangci-lint": build_golangci_lint_job,
    "clippy": build_clippy_job,
    "pytest": build_pytest_job,
    "cppcheck": build_cppcheck_job,
    "dotnet-format": build_dotnet_format_job,
    "checkstyle": build_checkstyle_job,
}


# ============ Language Defaults ============


def default_linter_jobs(language):
    """Get default linter jobs for a language when no toolchain profile exists."""
    lang = (language or "").lower()

    if lang == "python":
        return {"ruff": build_ruff_job(), "pytest": build_pytest_job()}
    elif lang in ("javascript", "typescript"):
        return {"eslint": build_eslint_job()}
    elif lang == "go":
        return {"go-vet": build_go_vet_job()}
    elif lang == "rust":
        return {"clippy": build_clippy_job()}
    elif lang in ("c", "c++", "cpp"):
        return {"cppcheck": build_cppcheck_job()}
    elif lang in ("c#", "csharp"):
        return {"dotnet-format": build_dotnet_format_job()}
    elif lang in ("java", "kotlin"):
        return {"checkstyle": build_checkstyle_job()}
    else:
        # Generic: just checkout
        return {
            "generic": {
                "name": "generic",
                "steps": [
                    _LFS_CHECKOUT,
                    "- run: echo 'No language-specific static analysis configured'",
                ],
            }
        }


# ============ Workflow Builder ============


def build_jobs_from_toolchain(toolchain_profile, language):
    """Build static analysis jobs matching the upstream repo's toolchain.

    Args:
        toolchain_profile: Dict from aggregator with linters, formatters, etc.
                           Can be None.
        language: Detected language string (fallback when no profile).
    Returns:
        Dict of job_name -> job_dict.
    """
    if not toolchain_profile:
        return default_linter_jobs(language)

    jobs = {}

    # Match linters from toolchain profile
    for linter in toolchain_profile.get("linters", []):
        tool = linter.get("tool", "").lower()
        builder = TOOL_BUILDERS.get(tool)
        if builder:
            jobs[tool] = builder()

    # Add CodeQL if the upstream repo uses it
    if "codeql" in [s.lower() for s in toolchain_profile.get("securityScanners", [])]:
        jobs["codeql"] = build_codeql_job(language)

    # If no tools matched from the profile, fall back to language defaults
    if not jobs:
        return default_linter_jobs(language)

    return jobs


def render_static_analysis_workflow(jobs):
    """Render jobs into a complete GitHub Actions workflow YAML string.

    The workflow uses workflow_dispatch with an inputs.ref parameter
    so vibedispatch controls exactly when analysis runs.

    Args:
        jobs: Dict of job_name -> job_dict (from build_jobs_from_toolchain).
    Returns:
        Complete workflow YAML as a string.
    """
    lines = [
        "name: Static Analysis (Stage 4b)",
        "on:",
        "  workflow_dispatch:",
        "    inputs:",
        "      ref:",
        "        description: 'Branch or SHA to analyze'",
        "        required: true",
        "",
        "permissions:",
        "  contents: write",
        "  pull-requests: write",
        "  security-events: write",
        "",
        "jobs:",
    ]

    for job_name, job in jobs.items():
        # Sanitize job name for YAML key (no dots, spaces)
        safe_name = job_name.replace(".", "-").replace(" ", "-")
        lines.append(f"  {safe_name}:")
        lines.append(f"    name: {job.get('name', job_name)}")
        lines.append("    runs-on: self-hosted")
        lines.append("    steps:")
        for step in job.get("steps", []):
            # Each step may be multi-line (e.g., uses with 'with:')
            for step_line in step.split("\n"):
                lines.append(f"      {step_line}")

    return "\n".join(lines) + "\n"
