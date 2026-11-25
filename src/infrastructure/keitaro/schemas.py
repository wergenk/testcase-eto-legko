from pydantic import BaseModel, ConfigDict

from src.core.dto.keitaro import (
    KeitaroCampaignDTO,
    KeitaroCatalogItemDTO,
    KeitaroID,
    KeitaroOfferDTO,
    KeitaroStreamOfferDTO,
)


class CampaignResponse(KeitaroCampaignDTO):
    model_config = ConfigDict(extra="ignore", frozen=True)


class CatalogItemResponse(KeitaroCatalogItemDTO):
    model_config = ConfigDict(extra="ignore", frozen=True)


class CampaignIdentityResponse(CatalogItemResponse):
    alias: str


class OfferResponse(KeitaroOfferDTO):
    model_config = ConfigDict(extra="ignore", frozen=True)


class StreamOfferResponse(KeitaroStreamOfferDTO):
    model_config = ConfigDict(extra="ignore", frozen=True)


class StreamResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: KeitaroID
    campaign_id: KeitaroID
    name: str
    offers: tuple[StreamOfferResponse, ...] = ()
