from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from src.api.di.database import StreamUowDepend
from src.api.di.keitaro import KeitaroGatewayDepend
from src.api.di.services import CampaignCreationServiceDepend, CampaignSyncServiceDepend
from src.api.schemas.campaign import CampaignStreamsResponse, CreateCampaignRequest
from src.api.schemas.common import PositiveID
from src.core.dto import (
    CampaignCreationAttempt,
    CampaignCreationResultDTO,
    CampaignFetchResultDTO,
    CreateCampaignDTO,
    FetchedStreamDTO,
)
from src.core.dto.keitaro import KeitaroCampaignSummaryDTO
from src.core.exceptions import StreamDraftNotFoundError

router = APIRouter(tags=["campaigns"])


@router.get("", response_model=list[KeitaroCampaignSummaryDTO])
async def list_campaigns(
    keitaro: KeitaroGatewayDepend,
    q: Annotated[str | None, Query(max_length=255)] = None,
) -> list[KeitaroCampaignSummaryDTO]:
    campaigns = await keitaro.list_campaigns()
    query = q.strip().casefold() if q else ""
    return [
        row
        for row in campaigns
        if not query or query in row.name.casefold() or query in str(row.id)
    ]


@router.post(
    "", response_model=CampaignCreationResultDTO, status_code=status.HTTP_201_CREATED
)
async def create_campaign(
    data: CreateCampaignRequest, service: CampaignCreationServiceDepend
) -> CampaignCreationResultDTO:
    return await service.create_campaign(CreateCampaignDTO(**data.model_dump()))


@router.get("/creation-attempts/{request_id}", response_model=CampaignCreationAttempt)
async def get_creation_attempt(
    request_id: UUID, uow: StreamUowDepend
) -> CampaignCreationAttempt:
    attempt = await uow.creations.get(request_id)
    if attempt is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Попытка создания кампании не найдена"
        )
    return attempt


@router.post("/{campaign_id}/fetch", response_model=CampaignStreamsResponse)
async def fetch_campaign(
    campaign_id: PositiveID, service: CampaignSyncServiceDepend
) -> CampaignFetchResultDTO:
    return await service.fetch_campaign(campaign_id)


@router.get("/{campaign_id}/streams", response_model=CampaignStreamsResponse)
async def get_local_streams(
    campaign_id: PositiveID, uow: StreamUowDepend
) -> CampaignFetchResultDTO:
    """Прочитать локальные черновики; запрос не запускает Fetch из Keitaro."""
    streams = await uow.streams.list_by_campaign(campaign_id)
    result = []
    for stream in streams:
        draft = await uow.drafts.get_by_stream(stream.id)
        if draft is None:
            raise StreamDraftNotFoundError(f"Черновик потока {stream.id} не найден")
        result.append(FetchedStreamDTO(stream=stream, draft=draft))
    return CampaignFetchResultDTO(
        keitaro_campaign_id=campaign_id, streams=tuple(result)
    )
