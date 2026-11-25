from functools import lru_cache

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.dto.campaign_creation import CampaignCreationDefaults


class DatabaseSettings(BaseModel):
    url: str


class KeitaroSettings(BaseModel):
    base_url: HttpUrl
    api_key: SecretStr = Field(min_length=1)
    timeout_seconds: float = Field(default=15, gt=0, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError(
                "Адрес API не должен содержать логин, пароль или параметры"
            )
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    db: DatabaseSettings
    # Миграции и локальный редактор могут работать без подключения к Keitaro.
    keitaro: KeitaroSettings | None = None
    campaign_creation: CampaignCreationDefaults | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
