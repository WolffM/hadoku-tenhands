"""Tests for workflow templates — static analysis workflow generation."""

import pytest

from services.workflow_templates import (
    build_ruff_job,
    build_eslint_job,
    build_biome_job,
    build_golangci_lint_job,
    build_go_vet_job,
    build_clippy_job,
    build_codeql_job,
    build_pytest_job,
    default_linter_jobs,
    build_jobs_from_toolchain,
    render_static_analysis_workflow,
    TOOL_BUILDERS,
)


class TestToolBuilders:
    """Tests for individual tool job builders."""

    def test_ruff_job_has_ruff_check(self):
        job = build_ruff_job()
        assert job["name"] == "ruff"
        steps_text = "\n".join(job["steps"])
        assert "ruff check" in steps_text
        assert "setup-python" in steps_text

    def test_eslint_job_has_eslint(self):
        job = build_eslint_job()
        assert job["name"] == "eslint"
        steps_text = "\n".join(job["steps"])
        assert "eslint" in steps_text
        assert "setup-node" in steps_text

    def test_biome_job(self):
        job = build_biome_job()
        assert "biome" in job["name"]
        steps_text = "\n".join(job["steps"])
        assert "biome check" in steps_text

    def test_golangci_lint_job(self):
        job = build_golangci_lint_job()
        steps_text = "\n".join(job["steps"])
        assert "golangci-lint" in steps_text
        assert "setup-go" in steps_text

    def test_go_vet_job(self):
        job = build_go_vet_job()
        steps_text = "\n".join(job["steps"])
        assert "go vet" in steps_text

    def test_clippy_job(self):
        job = build_clippy_job()
        steps_text = "\n".join(job["steps"])
        assert "clippy" in steps_text

    def test_codeql_job_python(self):
        job = build_codeql_job("python")
        steps_text = "\n".join(job["steps"])
        assert "codeql-action" in steps_text
        assert "python" in steps_text

    def test_codeql_job_javascript(self):
        job = build_codeql_job("javascript")
        steps_text = "\n".join(job["steps"])
        assert "javascript-typescript" in steps_text

    def test_codeql_job_go(self):
        job = build_codeql_job("go")
        steps_text = "\n".join(job["steps"])
        assert "languages: go" in steps_text

    def test_pytest_job(self):
        job = build_pytest_job()
        steps_text = "\n".join(job["steps"])
        assert "pytest" in steps_text

    def test_all_jobs_have_checkout(self):
        """Every job should start with actions/checkout."""
        for name, builder in TOOL_BUILDERS.items():
            job = builder()
            assert any("checkout" in s for s in job["steps"]), f"{name} missing checkout"

    def test_all_jobs_use_inputs_ref(self):
        """Every job should checkout the dispatched ref."""
        for name, builder in TOOL_BUILDERS.items():
            job = builder()
            assert any("inputs.ref" in s for s in job["steps"]), f"{name} missing inputs.ref"


class TestDefaultLinterJobs:
    """Tests for language-based fallback jobs."""

    def test_python_defaults(self):
        jobs = default_linter_jobs("python")
        assert "ruff" in jobs
        assert "pytest" in jobs

    def test_javascript_defaults(self):
        jobs = default_linter_jobs("javascript")
        assert "eslint" in jobs

    def test_typescript_defaults(self):
        jobs = default_linter_jobs("typescript")
        assert "eslint" in jobs

    def test_go_defaults(self):
        jobs = default_linter_jobs("go")
        assert "go-vet" in jobs

    def test_rust_defaults(self):
        jobs = default_linter_jobs("rust")
        assert "clippy" in jobs

    def test_unknown_language_returns_generic(self):
        jobs = default_linter_jobs("cobol")
        assert "generic" in jobs

    def test_none_language_returns_generic(self):
        jobs = default_linter_jobs(None)
        assert "generic" in jobs


class TestBuildJobsFromToolchain:
    """Tests for toolchain-profile-driven job selection."""

    def test_matches_ruff_from_profile(self):
        profile = {"linters": [{"tool": "ruff", "configFile": "ruff.toml"}]}
        jobs = build_jobs_from_toolchain(profile, "python")
        assert "ruff" in jobs

    def test_matches_eslint_from_profile(self):
        profile = {"linters": [{"tool": "eslint", "configFile": ".eslintrc.json"}]}
        jobs = build_jobs_from_toolchain(profile, "javascript")
        assert "eslint" in jobs

    def test_matches_multiple_tools(self):
        profile = {
            "linters": [
                {"tool": "ruff"},
                {"tool": "eslint"},
            ],
        }
        jobs = build_jobs_from_toolchain(profile, "python")
        assert "ruff" in jobs
        assert "eslint" in jobs

    def test_adds_codeql_when_in_profile(self):
        profile = {
            "linters": [{"tool": "ruff"}],
            "securityScanners": ["codeql"],
        }
        jobs = build_jobs_from_toolchain(profile, "python")
        assert "ruff" in jobs
        assert "codeql" in jobs

    def test_falls_back_to_defaults_when_no_tools_match(self):
        profile = {"linters": [{"tool": "unknown-linter"}]}
        jobs = build_jobs_from_toolchain(profile, "python")
        # Should fall back to python defaults
        assert "ruff" in jobs

    def test_falls_back_when_profile_is_none(self):
        jobs = build_jobs_from_toolchain(None, "go")
        assert "go-vet" in jobs

    def test_falls_back_when_profile_is_empty(self):
        jobs = build_jobs_from_toolchain({}, "python")
        assert "ruff" in jobs


class TestRenderWorkflow:
    """Tests for the complete workflow YAML rendering."""

    def test_render_has_workflow_dispatch(self):
        jobs = {"ruff": build_ruff_job()}
        yaml = render_static_analysis_workflow(jobs)
        assert "workflow_dispatch" in yaml
        assert "inputs:" in yaml
        assert "ref:" in yaml

    def test_render_has_permissions(self):
        jobs = {"ruff": build_ruff_job()}
        yaml = render_static_analysis_workflow(jobs)
        assert "permissions:" in yaml
        assert "contents: read" in yaml
        assert "security-events: write" in yaml

    def test_render_includes_all_jobs(self):
        jobs = {
            "ruff": build_ruff_job(),
            "codeql": build_codeql_job("python"),
        }
        yaml = render_static_analysis_workflow(jobs)
        assert "  ruff:" in yaml
        assert "  codeql:" in yaml

    def test_render_valid_yaml_structure(self):
        jobs = default_linter_jobs("python")
        yaml = render_static_analysis_workflow(jobs)
        assert yaml.startswith("name:")
        assert "jobs:" in yaml
        assert "runs-on: ubuntu-latest" in yaml

    def test_render_stage_4b_label(self):
        jobs = {"ruff": build_ruff_job()}
        yaml = render_static_analysis_workflow(jobs)
        assert "Stage 4b" in yaml
