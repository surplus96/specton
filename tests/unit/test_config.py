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
