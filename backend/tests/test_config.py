import pytest

from airsight.core.config import Settings


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@example:5432/test")
    monkeypatch.setenv("PURPLEAIR_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://user:pw@example:5432/test"
    assert settings.purpleair_key is not None
    assert settings.purpleair_key.get_secret_value() == "test-key"


def test_keys_are_hidden_when_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PURPLEAIR_KEY", "test-key")

    settings = Settings(_env_file=None)

    assert "test-key" not in repr(settings)
    assert "test-key" not in str(settings.model_dump())


def test_missing_keys_default_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PURPLEAIR_KEY", raising=False)
    monkeypatch.delenv("AIRNOW_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.purpleair_key is None
    assert settings.airnow_key is None
