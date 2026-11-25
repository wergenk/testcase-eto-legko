from datetime import UTC, datetime
from unittest.mock import Mock, create_autospec

import pytest

from src.core.dto import (
    DraftOfferDTO,
    KeitaroStreamDTO,
    KeitaroStreamOfferDTO,
    StreamDraft,
)
from src.core.exceptions import KeitaroError
from src.core.interfaces import KeitaroGateway, StreamUnitOfWork
from src.core.interfaces.repositories import StreamDraftRepository, StreamRepository
from src.core.services import CampaignSyncService


@pytest.mark.asyncio
@pytest.mark.parametrize("campaign_id", [0, -1, True, "367", 1.5])
async def test_invalid_campaign_id_does_not_call_gateway_or_uow(
    campaign_id: object,
) -> None:
    gateway = create_autospec(KeitaroGateway, instance=True)
    factory = Mock()
    with pytest.raises(ValueError):
        await CampaignSyncService(factory, gateway).fetch_campaign(campaign_id)
    factory.assert_not_called()
    gateway.get_campaign_streams.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_kind", ["foreign", "duplicate_stream", "duplicate_offer"]
)
async def test_invalid_remote_data_does_not_write_database(invalid_kind: str) -> None:
    gateway = create_autospec(KeitaroGateway, instance=True)
    uow = create_autospec(StreamUnitOfWork, instance=True)
    uow.__aenter__.return_value = uow
    uow.__aexit__.return_value = False
    uow.streams = create_autospec(StreamRepository, instance=True)
    uow.drafts = create_autospec(StreamDraftRepository, instance=True)
    uow.streams.list_by_campaign.return_value = []
    factory = Mock(return_value=uow)
    link = KeitaroStreamOfferDTO(offer_id=1, share=50, state="active")
    stream = KeitaroStreamDTO(id=1, campaign_id=367, name="Test", raw_payload={})
    if invalid_kind == "foreign":
        streams = [stream.model_copy(update={"campaign_id": 999})]
    elif invalid_kind == "duplicate_stream":
        streams = [stream, stream]
    else:
        streams = [stream.model_copy(update={"offers": (link, link)})]
    gateway.get_campaign_streams.return_value = streams
    with pytest.raises(KeitaroError):
        await CampaignSyncService(factory, gateway).fetch_campaign(367)
    uow.streams.create.assert_not_called()
    uow.drafts.update.assert_not_called()
    uow.commit.assert_not_called()
    gateway.list_offers.assert_not_called()


@pytest.mark.parametrize(
    "field",
    ["share", "is_pinned", "is_active", "name", "position", "membership", "order"],
)
def test_dirty_state_detects_edits_but_not_tuple_order(field: str) -> None:
    now = datetime.now(UTC)
    first = DraftOfferDTO(
        keitaro_offer_id=1,
        name="One",
        share=50,
        is_pinned=False,
        is_active=True,
        position=0,
    )
    second = first.model_copy(update={"keitaro_offer_id": 2, "position": 1})
    baseline = (first, second)
    values = {
        "share": 40,
        "is_pinned": True,
        "is_active": False,
        "name": "Changed",
        "position": 2,
    }
    if field == "order":
        current = tuple(reversed(baseline))
    elif field == "membership":
        current = (first,)
    else:
        current = (first.model_copy(update={field: values[field]}), second)
    draft = StreamDraft(
        id=1,
        stream_id=1,
        base_snapshot_id=1,
        revision=1,
        created_at=now,
        updated_at=now,
        offers=current,
        base_editor_state=baseline,
    )
    assert draft.is_dirty == (field != "order")
