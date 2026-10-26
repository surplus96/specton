import pytest

from specton.config import Settings


def test_settings_reads_prefixed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTON_MAX_REWORK_ITERATIONS", "1")

    settings = Settings(_env_file=None)

    assert settings.max_rework_iterations == 1


def test_settings_rejects_non_positive_upload_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTON_MAX_UPLOAD_MB", "0")

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_api_key_is_not_exposed_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTON_OPENAI_API_KEY", "sk-test-secret")

    settings = Settings(_env_file=None)

    assert "sk-test-secret" not in repr(settings)


ADR_0007_DEFAULTS = {
    "design_model": "gpt-6.1-sol",
    "review_model": "gpt-6-luna",
    "design_reasoning_effort": "medium",
    "review_reasoning_effort": "low",
    "llm_timeout_seconds": 120,
    "llm_api_retries": 3,
    "llm_concurrency": 4,
    "max_output_tokens": 8_000,
    "max_tokens_per_run": 400_000,
    "run_timeout_seconds": 900,
    "max_structured_retries": 2,
}


def test_llm_defaults_follow_adr_0007(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ADR_0007_DEFAULTS:
        monkeypatch.delenv(f"SPECTON_{name.upper()}", raising=False)

    settings = Settings(_env_file=None)

    assert {name: getattr(settings, name) for name in ADR_0007_DEFAULTS} == ADR_0007_DEFAULTS


def test_settings_rejects_unknown_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECTON_DESIGN_REASONING_EFFORT", "extreme")

    with pytest.raises(ValueError):
        Settings(_env_file=None)
