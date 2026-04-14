"""Unit tests for backend.temporal.config — Phase 1A.4."""

import pytest

from temporal import config as cfg


def test_load_config_uses_defaults(monkeypatch):
    monkeypatch.delenv("TEMPORAL_HOST", raising=False)
    monkeypatch.delenv("TEMPORAL_NAMESPACE", raising=False)
    monkeypatch.delenv("TEMPORAL_TASK_QUEUE", raising=False)

    c = cfg.load_config()
    assert c.host == "localhost:7233"
    assert c.namespace == "crimson-kitty"
    assert c.task_queue == "crimson-kitty-tq"


def test_load_config_honors_overrides(monkeypatch):
    monkeypatch.setenv("TEMPORAL_HOST", "temporal.internal:7233")
    monkeypatch.setenv("TEMPORAL_NAMESPACE", "test-ns")
    monkeypatch.setenv("TEMPORAL_TASK_QUEUE", "test-tq")

    c = cfg.load_config()
    assert c.host == "temporal.internal:7233"
    assert c.namespace == "test-ns"
    assert c.task_queue == "test-tq"


def test_load_config_returns_frozen_dataclass():
    c = cfg.load_config()
    with pytest.raises((AttributeError, TypeError)):
        c.host = "mutated"  # type: ignore[misc]


def test_validate_judge_credentials_passes_when_token_set(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    cfg.validate_judge_credentials()  # no raise


def test_validate_judge_credentials_raises_when_token_missing(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with pytest.raises(cfg.MissingConfigError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        cfg.validate_judge_credentials()


def test_validate_judge_credentials_treats_whitespace_as_missing(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "   ")
    with pytest.raises(cfg.MissingConfigError):
        cfg.validate_judge_credentials()
