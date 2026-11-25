import pytest
from pydantic import ValidationError

from src.config import KeitaroSettings, Settings


def test_keitaro_settings_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB__URL", "postgresql+asyncpg://localhost/test")
    monkeypatch.setenv("KEITARO__BASE_URL", "https://keitaro.example/admin_api/v1")
    monkeypatch.setenv("KEITARO__API_KEY", "test-api-key")
    monkeypatch.setenv("KEITARO__TIMEOUT_SECONDS", "8")
    settings = Settings(_env_file=None)
    assert settings.keitaro is not None
    assert settings.keitaro.timeout_seconds == 8
    assert settings.keitaro.api_key.get_secret_value() == "test-api-key"
    assert "test-api-key" not in repr(settings)


def test_migrations_do_not_require_keitaro_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "KEITARO",
        "KEITARO__BASE_URL",
        "KEITARO__API_KEY",
        "KEITARO__TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(
        db={"url": "postgresql+asyncpg://localhost/test"}, _env_file=None
    )
    assert settings.keitaro is None


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_is_rejected(timeout: float) -> None:
    with pytest.raises(ValidationError):
        KeitaroSettings(
            base_url="https://keitaro.example/", api_key="test", timeout_seconds=timeout
        )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://keitaro.example/",
        "https://user:password@keitaro.example/",
        "https://keitaro.example/?api_key=secret",
        "https://keitaro.example/#secret",
    ],
)
def test_invalid_api_url_is_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        KeitaroSettings(base_url=url, api_key="test")


def test_empty_api_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        KeitaroSettings(base_url="https://keitaro.example/", api_key="")
