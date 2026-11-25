"""Проверка Fetch на настоящих PostgreSQL-репозиториях и UOW."""

import asyncio
from functools import partial
from unittest.mock import Mock, create_autospec, patch

import pytest
from sqlalchemy import func, select

from src.core.dto import (
    CreateStreamDTO,
    KeitaroOfferDTO,
    KeitaroStreamDTO,
    KeitaroStreamOfferDTO,
)
from src.core.exceptions import (
    KeitaroError,
    KeitaroNotFoundError,
    KeitaroTimeoutError,
    StreamDraftConflictError,
)
from src.core.interfaces import KeitaroGateway
from src.core.services import CampaignSyncService, StreamDraftService
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.models import StreamSnapshotORM
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy

pytestmark = pytest.mark.asyncio


def remote_stream(
    stream_id: int,
    links: tuple[tuple[int, int, str], ...] = (),
    *,
    name: str = "Offers",
) -> KeitaroStreamDTO:
    offers = tuple(
        KeitaroStreamOfferDTO(offer_id=offer_id, share=share, state=state)
        for offer_id, share, state in links
    )
    return KeitaroStreamDTO(
        id=stream_id,
        campaign_id=367,
        name=name,
        offers=offers,
        raw_payload={
            "id": stream_id,
            "campaign_id": 367,
            "name": name,
            "offers": [offer.model_dump() for offer in offers],
            "filters": []
            if links
            else [{"name": "country", "mode": "accept", "payload": ["AU"]}],
            "action_payload": "" if links else "https://www.google.com/",
        },
    )


@pytest.fixture
def gateway() -> Mock:
    api = create_autospec(KeitaroGateway, instance=True, spec_set=True)
    api.get_campaign_streams.return_value = [
        remote_stream(667, name="GEO"),
        remote_stream(
            682, ((18003, 34, "active"), (18001, 33, "active"), (18002, 33, "active"))
        ),
    ]
    api.list_offers.return_value = [
        KeitaroOfferDTO(id=offer_id, name=f"Offer {offer_id}", state="active")
        for offer_id in (18001, 18002, 18003, 18004)
    ]
    return api


async def snapshot_count(manager: AsyncDatabaseSessionManager) -> int:
    async with manager.session() as session:
        return await session.scalar(select(func.count()).select_from(StreamSnapshotORM))


async def test_initial_fetch_persists_both_streams_and_baselines(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    service = CampaignSyncService(partial(StreamUnitOfWorkSQLAlchemy, manager), gateway)
    result = await service.fetch_campaign(367)

    assert result.keitaro_campaign_id == 367
    assert len(result.streams) == 2
    geo, offers = result.streams
    assert geo.draft.offers == ()
    assert [offer.share for offer in offers.draft.offers] == [34, 33, 33]
    assert [offer.name for offer in offers.draft.offers] == [
        "Offer 18003",
        "Offer 18001",
        "Offer 18002",
    ]
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        for fetched, remote in zip(
            result.streams, gateway.get_campaign_streams.return_value, strict=True
        ):
            assert fetched.stream.keitaro_stream_id == remote.id
            assert fetched.stream.id != remote.id
            assert await uow.drafts.get_by_stream(fetched.stream.id) == fetched.draft
            assert fetched.draft.revision == 1 and not fetched.draft.is_dirty
            assert fetched.draft.offers == fetched.draft.base_editor_state
            snapshot = await uow.snapshots.get(fetched.draft.base_snapshot_id)
            assert snapshot is not None and snapshot.payload == remote.raw_payload
    gateway.list_offers.assert_awaited_once()
    gateway.replace_stream_offers.assert_not_called()


async def test_repeat_fetch_updates_remote_shares_preserves_pins_and_archive(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    service = CampaignSyncService(factory, gateway)
    first = await service.fetch_campaign(367)
    draft = first.streams[1].draft
    async with factory() as uow:
        # Имитация ранее опубликованного локального закрепления.
        baseline = tuple(
            offer.model_copy(update={"is_pinned": offer.keitaro_offer_id == 18003})
            for offer in draft.offers
        )
        await uow.drafts.update(
            draft.model_copy(
                update={
                    "offers": baseline,
                    "base_editor_state": baseline,
                }
            ),
            expected_revision=1,
        )
        await uow.commit()

    gateway.get_campaign_streams.return_value = [
        remote_stream(667, name="Renamed GEO"),
        remote_stream(682, ((18004, 50, "active"), (18003, 50, "active"))),
    ]
    second = await service.fetch_campaign(367)
    refreshed = second.streams[1].draft
    assert second.streams[0].stream.name == "Renamed GEO"
    assert [row.keitaro_offer_id for row in refreshed.offers] == [
        18004,
        18003,
        18001,
        18002,
    ]
    assert [row.share for row in refreshed.offers] == [50, 50, 0, 0]
    assert refreshed.offers[1].is_pinned
    assert all(not row.is_active for row in refreshed.offers[2:])
    assert refreshed.base_snapshot_id != draft.base_snapshot_id
    assert refreshed.id == draft.id and refreshed.revision == 3
    assert refreshed.offers == refreshed.base_editor_state
    assert not refreshed.is_dirty

    third = await service.fetch_campaign(367)
    assert third.streams[1].draft.offers == refreshed.offers
    assert third.streams[1].stream.id == first.streams[1].stream.id
    assert await snapshot_count(manager) == 6
    async with factory() as uow:
        assert len(await uow.streams.list_by_campaign(367)) == 2
        assert await uow.snapshots.get(draft.base_snapshot_id) is not None


async def test_fetch_conflict_does_not_touch_any_stream_or_snapshot(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    service = CampaignSyncService(factory, gateway)
    first = await service.fetch_campaign(367)
    async with factory() as uow:
        editor = StreamDraftService(uow.drafts, gateway)
        dirty = await editor.remove_offer(
            first.streams[1].draft.id, 18003, expected_revision=1
        )
        await uow.commit()
    gateway.get_campaign_streams.return_value = [
        remote_stream(667, name="Changed GEO"),
        remote_stream(700),
    ]
    with pytest.raises(StreamDraftConflictError, match="Cancel или Push"):
        await service.fetch_campaign(367)
    assert await snapshot_count(manager) == 2
    async with factory() as uow:
        assert await uow.drafts.get(dirty.id) == dirty
        assert (
            await uow.streams.get(first.streams[0].stream.id) == first.streams[0].stream
        )
        assert await uow.streams.get_by_keitaro_id(700) is None


async def test_cancel_after_fetch_keeps_external_archive_and_does_not_recalculate(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    service = CampaignSyncService(factory, gateway)
    await service.fetch_campaign(367)
    gateway.get_campaign_streams.return_value = [
        remote_stream(682, ((18003, 60, "active"), (18002, 40, "active"))),
    ]
    fetched = (await service.fetch_campaign(367)).streams[0].draft
    assert [row.share for row in fetched.offers] == [60, 40, 0]
    async with factory() as uow:
        editor = StreamDraftService(uow.drafts, gateway)
        edited = await editor.pin_share(
            fetched.id, 18003, 25, expected_revision=fetched.revision
        )
        assert edited.is_dirty
        cancelled = await editor.cancel_changes(
            fetched.id, expected_revision=edited.revision
        )
        assert cancelled.offers == fetched.offers
        assert not cancelled.is_dirty
        await uow.commit()
    await service.fetch_campaign(367)


async def test_disabled_links_and_reappearing_offers(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    service = CampaignSyncService(partial(StreamUnitOfWorkSQLAlchemy, manager), gateway)
    await service.fetch_campaign(367)
    gateway.get_campaign_streams.return_value = [
        remote_stream(682, ((18001, 100, "active"), (18003, 34, "disabled"))),
    ]
    result = await service.fetch_campaign(367)
    by_id = {row.keitaro_offer_id: row for row in result.streams[0].draft.offers}
    assert by_id[18003].share == 0 and not by_id[18003].is_active
    assert not by_id[18002].is_active
    gateway.get_campaign_streams.return_value = [
        remote_stream(682, ((18003, 50, "active"), (18002, 50, "active"))),
    ]
    result = await service.fetch_campaign(367)
    by_id = {row.keitaro_offer_id: row for row in result.streams[0].draft.offers}
    assert by_id[18002].is_active and by_id[18003].is_active
    assert not by_id[18001].is_active and len(by_id) == 3


async def test_catalog_fallback_fetches_missing_offer_once(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    gateway.get_campaign_streams.return_value = [
        remote_stream(1, ((99, 100, "active"),)),
        remote_stream(2, ((99, 100, "active"),)),
    ]
    gateway.get_offer.return_value = KeitaroOfferDTO(
        id=99, name="Fallback", state="active"
    )
    result = await CampaignSyncService(
        partial(StreamUnitOfWorkSQLAlchemy, manager), gateway
    ).fetch_campaign(367)
    assert all(stream.draft.offers[0].name == "Fallback" for stream in result.streams)
    gateway.get_offer.assert_awaited_once_with(99)


async def test_empty_campaign_and_geo_do_not_require_catalog(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    service = CampaignSyncService(partial(StreamUnitOfWorkSQLAlchemy, manager), gateway)
    gateway.get_campaign_streams.return_value = []
    assert (await service.fetch_campaign(367)).streams == ()
    gateway.get_campaign_streams.return_value = [remote_stream(667, name="GEO")]
    assert (await service.fetch_campaign(367)).streams[0].draft.offers == ()
    gateway.list_offers.assert_not_called()


@pytest.mark.parametrize("failure", ["campaign", "catalog", "offer"])
async def test_remote_errors_leave_database_unchanged(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
    failure: str,
) -> None:
    if failure == "campaign":
        gateway.get_campaign_streams.side_effect = KeitaroNotFoundError()
    elif failure == "catalog":
        gateway.list_offers.side_effect = KeitaroTimeoutError()
    else:
        gateway.list_offers.return_value = []
        gateway.get_offer.side_effect = KeitaroNotFoundError()
    with pytest.raises(KeitaroError):
        await CampaignSyncService(
            partial(StreamUnitOfWorkSQLAlchemy, manager), gateway
        ).fetch_campaign(367)
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        assert await uow.streams.list_by_campaign(367) == []
    assert await snapshot_count(manager) == 0


async def test_late_revision_conflict_rolls_back_earlier_streams_and_snapshots(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    service = CampaignSyncService(factory, gateway)
    original = await service.fetch_campaign(367)
    gateway.get_campaign_streams.return_value[0] = remote_stream(667, name="New GEO")
    uow = factory()
    async with uow:
        repository_type = type(uow.drafts)
    original_update = repository_type.update

    async def update(
        repository: object, draft: object, *, expected_revision: int
    ) -> object:
        if draft.stream_id == original.streams[1].stream.id:
            return None
        return await original_update(
            repository, draft, expected_revision=expected_revision
        )

    with (
        patch.object(repository_type, "update", update),
        pytest.raises(StreamDraftConflictError),
    ):
        await service.fetch_campaign(367)
    assert await snapshot_count(manager) == 2
    async with factory() as reader:
        for saved in original.streams:
            assert await reader.streams.get(saved.stream.id) == saved.stream
            assert await reader.drafts.get(saved.draft.id) == saved.draft


async def test_two_initial_fetches_do_not_duplicate_streams_or_drafts(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    service = CampaignSyncService(factory, gateway)
    first, second = await asyncio.wait_for(
        asyncio.gather(service.fetch_campaign(367), service.fetch_campaign(367)),
        timeout=15,
    )
    assert [row.stream.id for row in first.streams] == [
        row.stream.id for row in second.streams
    ]
    assert [row.draft.id for row in first.streams] == [
        row.draft.id for row in second.streams
    ]
    assert sorted(
        [first.streams[0].draft.revision, second.streams[0].draft.revision]
    ) == [1, 2]
    async with factory() as uow:
        assert len(await uow.streams.list_by_campaign(367)) == 2


async def test_stream_linked_to_another_campaign_is_not_reassigned(
    manager: AsyncDatabaseSessionManager,
    gateway: Mock,
) -> None:
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    async with factory() as uow:
        await uow.streams.create(
            CreateStreamDTO(
                keitaro_stream_id=682, keitaro_campaign_id=999, name="Foreign"
            )
        )
        await uow.commit()
    with pytest.raises(KeitaroError):
        await CampaignSyncService(factory, gateway).fetch_campaign(367)
    async with factory() as uow:
        assert await uow.streams.list_by_campaign(367) == []
    assert await snapshot_count(manager) == 0
