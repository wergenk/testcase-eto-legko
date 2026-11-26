from fastapi import APIRouter

from src.api.di.database import StreamUowDepend
from src.api.di.services import CampaignSyncServiceDepend, StreamDraftServiceDepend
from src.api.schemas.common import PositiveID
from src.api.schemas.draft import (
    AddOfferRequest,
    PinShareRequest,
    RevisionRequest,
    StreamDraftResponse,
)
from src.core.dto import StreamDraft
from src.core.exceptions import StreamDraftNotFoundError

router = APIRouter(tags=["drafts"])


@router.get("/{draft_id}", response_model=StreamDraftResponse)
async def get_draft(draft_id: PositiveID, uow: StreamUowDepend) -> StreamDraft:
    draft = await uow.drafts.get(draft_id)
    if draft is None:
        raise StreamDraftNotFoundError(f"Черновик {draft_id} не найден")
    return draft


@router.post("/{draft_id}/offers", response_model=StreamDraftResponse)
async def add_offer(
    draft_id: PositiveID,
    data: AddOfferRequest,
    service: StreamDraftServiceDepend,
    uow: StreamUowDepend,
) -> StreamDraft:
    draft = await service.add_offer(
        draft_id, data.offer_id, expected_revision=data.expected_revision
    )
    await uow.commit()
    return draft


@router.delete("/{draft_id}/offers/{offer_id}", response_model=StreamDraftResponse)
async def remove_offer(
    draft_id: PositiveID,
    offer_id: PositiveID,
    data: RevisionRequest,
    service: StreamDraftServiceDepend,
    uow: StreamUowDepend,
) -> StreamDraft:
    draft = await service.remove_offer(
        draft_id, offer_id, expected_revision=data.expected_revision
    )
    await uow.commit()
    return draft


@router.post(
    "/{draft_id}/offers/{offer_id}/restore", response_model=StreamDraftResponse
)
async def restore_offer(
    draft_id: PositiveID,
    offer_id: PositiveID,
    data: RevisionRequest,
    service: StreamDraftServiceDepend,
    uow: StreamUowDepend,
) -> StreamDraft:
    draft = await service.restore_offer(
        draft_id, offer_id, expected_revision=data.expected_revision
    )
    await uow.commit()
    return draft


@router.put("/{draft_id}/offers/{offer_id}/pin", response_model=StreamDraftResponse)
async def pin_share(
    draft_id: PositiveID,
    offer_id: PositiveID,
    data: PinShareRequest,
    service: StreamDraftServiceDepend,
    uow: StreamUowDepend,
) -> StreamDraft:
    draft = await service.pin_share(
        draft_id, offer_id, data.share, expected_revision=data.expected_revision
    )
    await uow.commit()
    return draft


@router.delete("/{draft_id}/offers/{offer_id}/pin", response_model=StreamDraftResponse)
async def unpin_share(
    draft_id: PositiveID,
    offer_id: PositiveID,
    data: RevisionRequest,
    service: StreamDraftServiceDepend,
    uow: StreamUowDepend,
) -> StreamDraft:
    draft = await service.unpin_share(
        draft_id, offer_id, expected_revision=data.expected_revision
    )
    await uow.commit()
    return draft


@router.post("/{draft_id}/cancel", response_model=StreamDraftResponse)
async def cancel_changes(
    draft_id: PositiveID,
    data: RevisionRequest,
    service: StreamDraftServiceDepend,
    uow: StreamUowDepend,
) -> StreamDraft:
    draft = await service.cancel_changes(
        draft_id, expected_revision=data.expected_revision
    )
    await uow.commit()
    return draft


@router.post("/{draft_id}/push", response_model=StreamDraftResponse)
async def push_stream(
    draft_id: PositiveID, data: RevisionRequest, service: CampaignSyncServiceDepend
) -> StreamDraft:
    return await service.push_stream(draft_id, expected_revision=data.expected_revision)
