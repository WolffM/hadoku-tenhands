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


def test_validate_judge_credentials_passes_when_the_service_key_is_set(monkeypatch):
    monkeypatch.setenv("HADOKU_SERVICE_KEY", "key")
    cfg.validate_judge_credentials()  # no raise


def test_validate_judge_credentials_raises_when_the_service_key_is_missing(monkeypatch):
    monkeypatch.delenv("HADOKU_SERVICE_KEY", raising=False)
    with pytest.raises(cfg.MissingConfigError, match="KEY_SERVICE_TENHANDS"):
        cfg.validate_judge_credentials()


def test_validate_judge_credentials_treats_whitespace_as_missing(monkeypatch):
    monkeypatch.setenv("HADOKU_SERVICE_KEY", "   ")
    with pytest.raises(cfg.MissingConfigError):
        cfg.validate_judge_credentials()


def test_a_claude_token_in_the_environment_is_not_a_credential_any_more(monkeypatch):
    """tenhands leases; a token lying in the environment satisfies nothing."""
    monkeypatch.delenv("HADOKU_SERVICE_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_OAUTH_TOKEN_MATTH", "sk-ant-oat01-fake")
    with pytest.raises(cfg.MissingConfigError):
        cfg.validate_judge_credentials()
