from datetime import UTC, datetime
from unittest.mock import Mock, create_autospec

import pytest

from src.core.dto import DraftOfferDTO, StreamDraft
from src.core.exceptions import OfferShareError, StreamPublicationError
from src.core.interfaces import KeitaroGateway
from src.core.services import CampaignSyncService


def draft_with(offers: tuple[DraftOfferDTO, ...]) -> StreamDraft:
    now = datetime.now(UTC)
    return StreamDraft(
        id=1,
        stream_id=1,
        base_snapshot_id=1,
        revision=2,
        created_at=now,
        updated_at=now,
        offers=offers,
        base_editor_state=(),
    )


def row(offer_id: int, share: int, *, active: bool = True) -> DraftOfferDTO:
    return DraftOfferDTO(
        keitaro_offer_id=offer_id,
        name="Offer",
        share=share,
        is_active=active,
        is_pinned=False,
        position=offer_id,
    )


@pytest.mark.parametrize(
    "offers",
    [
        (row(1, 50),),
        (row(1, 100), row(2, 1)),
        (row(1, 50), row(1, 50)),
        (row(1, 100), row(2, 10, active=False)),
    ],
)
def test_invalid_distribution_cannot_be_published(
    offers: tuple[DraftOfferDTO, ...],
) -> None:
    with pytest.raises(OfferShareError):
        CampaignSyncService._publication_offers(draft_with(offers))


def test_archived_rows_and_pins_are_not_sent_to_keitaro() -> None:
    active = row(1, 100).model_copy(update={"is_pinned": True})
    result = CampaignSyncService._publication_offers(
        draft_with((active, row(2, 0, active=False)))
    )
    assert [offer.model_dump() for offer in result] == [
        {"offer_id": 1, "share": 100, "state": "active"}
    ]


@pytest.mark.parametrize(
    "offers",
    [
        None,
        "invalid",
        [None],
        [{}],
        [{"offer_id": 1, "share": 33.5, "state": "active"}],
        [{"offer_id": 1, "share": 100, "state": "active"}] * 2,
    ],
)
def test_corrupt_snapshot_cannot_be_used_as_publication_baseline(
    offers: object,
) -> None:
    with pytest.raises(StreamPublicationError):
        CampaignSyncService._snapshot_offer_signature({"offers": offers})


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, -1, True, "1", 1.5])
@pytest.mark.parametrize("field", ["draft_id", "expected_revision"])
async def test_invalid_publication_ids_do_not_start_transaction(
    value: object, field: str
) -> None:
    factory = Mock()
    api = create_autospec(KeitaroGateway, instance=True)
    args = {"draft_id": 1, "expected_revision": 1, field: value}
    with pytest.raises(ValueError):
        await CampaignSyncService(factory, api).push_stream(**args)
    factory.assert_not_called()
    api.get_stream.assert_not_called()
    api.replace_stream_offers.assert_not_called()
