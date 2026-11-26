from typing import Annotated

from fastapi import Depends, HTTPException, status

from src.core.dto import CampaignCreationDefaults
from src.core.services import (
    CampaignCreationService,
    CampaignSyncService,
    StreamDraftService,
)

from .database import StreamUowFactoryDepend
from .keitaro import KeitaroGatewayDepend, SettingsDepend


def get_campaign_sync_service(
    factory: StreamUowFactoryDepend, keitaro: KeitaroGatewayDepend
) -> CampaignSyncService:
    return CampaignSyncService(factory, keitaro)


def get_campaign_creation_service(
    factory: StreamUowFactoryDepend,
    keitaro: KeitaroGatewayDepend,
    settings: SettingsDepend,
) -> CampaignCreationService:
    if settings.campaign_creation is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Не настроены домен, группа и источник для создания кампаний",
        )
    defaults = CampaignCreationDefaults(**settings.campaign_creation.model_dump())
    return CampaignCreationService(factory, keitaro, defaults)


def get_stream_draft_service(
    factory: StreamUowFactoryDepend, keitaro: KeitaroGatewayDepend
) -> StreamDraftService:
    return StreamDraftService(factory, keitaro)


CampaignSyncServiceDepend = Annotated[
    CampaignSyncService, Depends(get_campaign_sync_service)
]
CampaignCreationServiceDepend = Annotated[
    CampaignCreationService, Depends(get_campaign_creation_service)
]
StreamDraftServiceDepend = Annotated[
    StreamDraftService, Depends(get_stream_draft_service)
]
