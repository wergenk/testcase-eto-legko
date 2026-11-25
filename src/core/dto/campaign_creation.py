from datetime import datetime
from typing import Literal
from uuid import UUID

import pycountry
from pydantic import Field, field_validator

from .base import FrozenBaseDTO
from .keitaro import KeitaroID


class CampaignCreationDefaults(FrozenBaseDTO):
    domain_id: KeitaroID
    group_id: KeitaroID
    traffic_source_id: KeitaroID


class CreateCampaignDTO(FrozenBaseDTO):
    request_id: UUID
    name: str = Field(min_length=1, max_length=255)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    offer_id: KeitaroID

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("country_code", mode="before")
    @classmethod
    def normalize_country(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("country_code")
    @classmethod
    def validate_country(cls, value: str) -> str:
        if pycountry.countries.get(alpha_2=value) is None:
            raise ValueError("Неизвестный код страны ISO 3166-1 alpha-2")
        return value


CreationStage = Literal["pending", "campaign", "geo", "offers", "active", "completed"]


class CampaignCreationAttempt(FrozenBaseDTO):
    request_id: UUID
    command: CreateCampaignDTO
    defaults: CampaignCreationDefaults
    stage: CreationStage = "pending"
    campaign_id: KeitaroID | None = None
    geo_stream_id: KeitaroID | None = None
    offers_stream_id: KeitaroID | None = None
    created_at: datetime
    updated_at: datetime


class CampaignCreationResultDTO(FrozenBaseDTO):
    request_id: UUID
    campaign_id: KeitaroID
    geo_stream_id: KeitaroID
    offers_stream_id: KeitaroID
