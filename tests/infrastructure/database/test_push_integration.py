"""Push: настоящая БД, управляемый тестовый gateway без внешних записей."""

import asyncio
from collections.abc import Callable, Sequence
from copy import deepcopy
from functools import partial
from unittest.mock import Mock, create_autospec, patch

import pytest
from sqlalchemy import func, select

from src.core.dto import (
    KeitaroOfferDTO,
    KeitaroStreamDTO,
    KeitaroStreamOfferDTO,
    KeitaroStreamOfferInputDTO,
    StreamDraft,
)
from src.core.exceptions import (
    KeitaroNotFoundError,
    KeitaroTimeoutError,
    StreamDraftConflictError,
    StreamDraftNotFoundError,
    StreamPublicationConflictError,
    StreamPublicationError,
)
from src.core.interfaces import KeitaroGateway, StreamUnitOfWork
from src.core.services import CampaignSyncService, StreamDraftService
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.models import StreamSnapshotORM
from src.infrastructure.database.repositories import StreamDraftSQLAlchemyRepository
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy

pytestmark = pytest.mark.asyncio
type Tracker = tuple[Mock, list[KeitaroStreamDTO]]


def remote(stream_id: int, offers: Sequence[KeitaroStreamOfferDTO]) -> KeitaroStreamDTO:
    return KeitaroStreamDTO(
        id=stream_id,
        campaign_id=367,
        name="Offers" if offers else "GEO",
        offers=tuple(offers),
        raw_payload={
            "id": stream_id,
            "campaign_id": 367,
            "name": "Offers" if offers else "GEO",
            "schema": "landings" if offers else "redirect",
            "offers": [offer.model_dump() for offer in offers],
            "filters": [] if offers else [{"name": "country", "payload": ["AU"]}],
            "action_payload": "" if offers else "https://www.google.com/",
        },
    )


@pytest.fixture
def tracker() -> Tracker:
    api = create_autospec(KeitaroGateway, instance=True, spec_set=True)
    streams = [
        remote(667, ()),
        remote(
            682,
            [
                KeitaroStreamOfferDTO(offer_id=offer_id, share=share, state="active")
                for offer_id, share in [(18003, 34), (18001, 33), (18002, 33)]
            ],
        ),
    ]
    api.get_campaign_streams.side_effect = lambda campaign_id: deepcopy(streams)
    api.get_stream.side_effect = lambda stream_id: deepcopy(
        next(row for row in streams if row.id == stream_id)
    )
    api.list_offers.return_value = [
        KeitaroOfferDTO(id=value, name=f"Offer {value}", state="active")
        for value in [18001, 18002, 18003, 18004]
    ]
    api.get_offer.side_effect = lambda offer_id: KeitaroOfferDTO(
        id=offer_id, name=f"Offer {offer_id}", state="active"
    )

    async def replace(
        stream_id: int, offers: Sequence[KeitaroStreamOfferInputDTO]
    ) -> KeitaroStreamDTO:
        index = next(index for index, row in enumerate(streams) if row.id == stream_id)
        previous = streams[index]
        links = tuple(KeitaroStreamOfferDTO(**offer.model_dump()) for offer in offers)
        payload = deepcopy(previous.raw_payload)
        payload["offers"] = [offer.model_dump() for offer in links]
        streams[index] = previous.model_copy(
            update={"offers": links, "raw_payload": payload}
        )
        return deepcopy(streams[index])

    api.replace_stream_offers.side_effect = replace
    return api, streams


async def seed_dirty(
    factory: Callable[[], StreamUnitOfWork],
    api: KeitaroGateway,
) -> StreamDraft:
    result = await CampaignSyncService(factory, api).fetch_campaign(367)
    async with factory() as uow:
        dirty = await StreamDraftService(uow.drafts, api).pin_share(
            result.streams[1].draft.id, 18003, 25, expected_revision=1
        )
        await uow.commit()
    return dirty


async def count_snapshots(manager: AsyncDatabaseSessionManager) -> int:
    async with manager.session() as session:
        return await session.scalar(select(func.count()).select_from(StreamSnapshotORM))


async def test_push_publishes_preserves_pin_and_rebases_snapshot(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    saved = await CampaignSyncService(factory, api).push_stream(
        draft.id, expected_revision=2
    )
    assert not saved.is_dirty and saved.revision == 3
    assert saved.offers[0].is_pinned and saved.offers[0].share == 25
    assert saved.offers == draft.offers == saved.base_editor_state
    assert saved.base_snapshot_id != draft.base_snapshot_id
    sent = api.replace_stream_offers.await_args.args
    assert sent[0] == 682
    assert [offer.share for offer in sent[1]] == [25, 38, 37]
    async with factory() as uow:
        assert await uow.drafts.get(draft.id) == saved
        snapshot = await uow.snapshots.get(saved.base_snapshot_id)
        assert snapshot is not None and snapshot.payload == streams[1].raw_payload
        assert await uow.snapshots.get(draft.base_snapshot_id) is not None


async def test_remove_and_restore_keep_local_archive(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    imported = await CampaignSyncService(factory, api).fetch_campaign(367)
    async with factory() as uow:
        draft = await StreamDraftService(uow.drafts, api).remove_offer(
            imported.streams[1].draft.id, 18001, expected_revision=1
        )
        await uow.commit()
    service = CampaignSyncService(factory, api)
    published = await service.push_stream(draft.id, expected_revision=2)
    assert [row.offer_id for row in streams[1].offers] == [18003, 18002]
    archived = next(row for row in published.offers if row.keitaro_offer_id == 18001)
    assert not archived.is_active and archived.share == 0
    async with factory() as uow:
        restored = await StreamDraftService(uow.drafts, api).restore_offer(
            draft.id, 18001, expected_revision=3
        )
        await uow.commit()
    saved = await service.push_stream(draft.id, expected_revision=restored.revision)
    assert all(row.is_active for row in saved.offers)
    assert len(streams[1].offers) == 3 and not saved.is_dirty


async def test_empty_active_set_clears_remote_offers_but_keeps_archive(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    async with factory() as uow:
        editor = StreamDraftService(uow.drafts, api)
        for offer_id in [18003, 18001, 18002]:
            draft = await editor.remove_offer(
                draft.id, offer_id, expected_revision=draft.revision
            )
        await uow.commit()
    saved = await CampaignSyncService(factory, api).push_stream(
        draft.id, expected_revision=draft.revision
    )
    assert streams[1].offers == ()
    assert len(saved.offers) == 3 and all(not row.is_active for row in saved.offers)
    assert api.replace_stream_offers.await_args.args[1] == ()


async def test_pin_only_change_is_committed_without_put(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, _ = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    imported = await CampaignSyncService(factory, api).fetch_campaign(367)
    async with factory() as uow:
        dirty = await StreamDraftService(uow.drafts, api).pin_share(
            imported.streams[1].draft.id, 18003, 34, expected_revision=1
        )
        await uow.commit()
    result = await CampaignSyncService(factory, api).push_stream(
        dirty.id, expected_revision=2
    )
    assert not result.is_dirty and result.offers[0].is_pinned
    api.replace_stream_offers.assert_not_called()


async def test_clean_push_is_noop_and_stale_revision_is_rejected(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, _ = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    service = CampaignSyncService(factory, api)
    imported = await service.fetch_campaign(367)
    draft = imported.streams[1].draft
    with pytest.raises(StreamDraftConflictError):
        await service.push_stream(draft.id, expected_revision=99)
    assert await service.push_stream(draft.id, expected_revision=1) == draft
    assert await count_snapshots(manager) == 2
    api.get_stream.assert_not_called()
    api.replace_stream_offers.assert_not_called()


async def test_missing_draft_does_not_call_gateway(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, _ = tracker
    with pytest.raises(StreamDraftNotFoundError):
        await CampaignSyncService(
            partial(StreamUnitOfWorkSQLAlchemy, manager), api
        ).push_stream(999, expected_revision=1)
    api.get_stream.assert_not_called()


@pytest.mark.parametrize("change", ["offers", "schema"])
async def test_external_change_is_not_overwritten(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
    change: str,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    if change == "schema":
        streams[1].raw_payload["schema"] = "redirect"
    else:
        streams[1] = remote(
            682, (KeitaroStreamOfferDTO(offer_id=18004, share=100, state="active"),)
        )
    with pytest.raises(StreamPublicationConflictError):
        await CampaignSyncService(factory, api).push_stream(
            draft.id, expected_revision=2
        )
    async with factory() as uow:
        assert await uow.drafts.get(draft.id) == draft
    assert await count_snapshots(manager) == 2
    api.replace_stream_offers.assert_not_called()


async def test_unrelated_external_settings_are_preserved_in_new_snapshot(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    streams[1].raw_payload["filters"] = [{"name": "device_type", "payload": ["mobile"]}]
    saved = await CampaignSyncService(factory, api).push_stream(
        draft.id, expected_revision=2
    )
    async with factory() as uow:
        snapshot = await uow.snapshots.get(saved.base_snapshot_id)
        assert snapshot.payload["filters"] == streams[1].raw_payload["filters"]


@pytest.mark.parametrize("stage", ["read", "write"])
async def test_keitaro_error_keeps_dirty_state(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
    stage: str,
) -> None:
    api, _ = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    if stage == "read":
        api.get_stream.side_effect = KeitaroNotFoundError()
        error_type = KeitaroNotFoundError
    else:
        api.replace_stream_offers.side_effect = KeitaroTimeoutError()
        error_type = KeitaroTimeoutError
    with pytest.raises(error_type):
        await CampaignSyncService(factory, api).push_stream(
            draft.id, expected_revision=2
        )
    async with factory() as uow:
        assert await uow.drafts.get(draft.id) == draft
    assert await count_snapshots(manager) == 2


@pytest.mark.parametrize("failure", ["timeout_after_put", "snapshot", "commit"])
async def test_retry_recovers_applied_put_without_repeating_write(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
    failure: str,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    service = CampaignSyncService(factory, api)
    original_put = api.replace_stream_offers.side_effect
    if failure == "timeout_after_put":

        async def put_then_timeout(
            stream_id: int, offers: Sequence[KeitaroStreamOfferInputDTO]
        ) -> KeitaroStreamDTO:
            await original_put(stream_id, offers)
            raise KeitaroTimeoutError()

        api.replace_stream_offers.side_effect = put_then_timeout
        with pytest.raises(KeitaroTimeoutError):
            await service.push_stream(draft.id, expected_revision=2)
        api.replace_stream_offers.side_effect = original_put
    elif failure == "snapshot":
        async with factory() as uow:
            snapshot_repository_type = type(uow.snapshots)
        with patch.object(
            snapshot_repository_type, "create", side_effect=RuntimeError("DB down")
        ):
            with pytest.raises(RuntimeError, match="DB down"):
                await service.push_stream(draft.id, expected_revision=2)
    else:
        with patch.object(
            StreamUnitOfWorkSQLAlchemy,
            "commit",
            side_effect=RuntimeError("Commit failed"),
        ):
            with pytest.raises(RuntimeError, match="Commit failed"):
                await service.push_stream(draft.id, expected_revision=2)

    assert [row.share for row in streams[1].offers] == [25, 38, 37]
    async with factory() as uow:
        assert await uow.drafts.get(draft.id) == draft
    assert await count_snapshots(manager) == 2
    recovered = await service.push_stream(draft.id, expected_revision=2)
    assert not recovered.is_dirty and recovered.revision == 3
    assert api.replace_stream_offers.await_count == 1


async def test_unexpected_put_response_does_not_advance_local_baseline(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, streams = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    api.replace_stream_offers.side_effect = None
    api.replace_stream_offers.return_value = streams[1]
    with pytest.raises(StreamPublicationError):
        await CampaignSyncService(factory, api).push_stream(
            draft.id, expected_revision=2
        )
    async with factory() as uow:
        assert await uow.drafts.get(draft.id) == draft
    assert await count_snapshots(manager) == 2


async def test_two_simultaneous_pushes_have_one_put_and_one_version_conflict(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, _ = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    service = CampaignSyncService(factory, api)
    results = await asyncio.wait_for(
        asyncio.gather(
            service.push_stream(draft.id, expected_revision=2),
            service.push_stream(draft.id, expected_revision=2),
            return_exceptions=True,
        ),
        timeout=10,
    )
    assert sum(isinstance(result, StreamDraft) for result in results) == 1
    assert sum(isinstance(result, StreamDraftConflictError) for result in results) == 1
    assert api.replace_stream_offers.await_count == 1


async def test_editor_cannot_write_during_push_and_old_revision_fails_after_commit(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, _ = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    entered_put, release_put, update_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    original_put = api.replace_stream_offers.side_effect
    original_update = StreamDraftSQLAlchemyRepository.update

    async def slow_put(
        stream_id: int, offers: Sequence[KeitaroStreamOfferInputDTO]
    ) -> KeitaroStreamDTO:
        entered_put.set()
        await release_put.wait()
        return await original_put(stream_id, offers)

    async def watch_update(
        repository: StreamDraftSQLAlchemyRepository,
        changed: StreamDraft,
        *,
        expected_revision: int,
    ) -> StreamDraft | None:
        if changed.offers != draft.offers:
            update_started.set()
        return await original_update(
            repository, changed, expected_revision=expected_revision
        )

    async def edit() -> StreamDraft:
        async with factory() as uow:
            return await StreamDraftService(uow.drafts, api).remove_offer(
                draft.id, 18001, expected_revision=2
            )

    api.replace_stream_offers.side_effect = slow_put
    with patch.object(StreamDraftSQLAlchemyRepository, "update", watch_update):
        pushing = asyncio.create_task(
            CampaignSyncService(factory, api).push_stream(draft.id, expected_revision=2)
        )
        await asyncio.wait_for(entered_put.wait(), 5)
        editing = asyncio.create_task(edit())
        try:
            await asyncio.wait_for(update_started.wait(), 5)
            assert not editing.done()
        finally:
            release_put.set()
        await asyncio.wait_for(pushing, 5)
        with pytest.raises(StreamDraftConflictError):
            await asyncio.wait_for(editing, 5)


async def test_fetch_waits_for_push_and_imports_published_state(
    manager: AsyncDatabaseSessionManager,
    tracker: Tracker,
) -> None:
    api, _ = tracker
    factory = partial(StreamUnitOfWorkSQLAlchemy, manager)
    draft = await seed_dirty(factory, api)
    entered_put, release_put, fetch_lock = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    original_put = api.replace_stream_offers.side_effect
    original_lock = StreamUnitOfWorkSQLAlchemy.lock_campaign

    async def slow_put(
        stream_id: int, offers: Sequence[KeitaroStreamOfferInputDTO]
    ) -> KeitaroStreamDTO:
        entered_put.set()
        await release_put.wait()
        return await original_put(stream_id, offers)

    async def lock(uow: StreamUnitOfWorkSQLAlchemy, campaign_id: int) -> None:
        if entered_put.is_set():
            fetch_lock.set()
        await original_lock(uow, campaign_id)

    api.replace_stream_offers.side_effect = slow_put
    api.get_campaign_streams.reset_mock()
    service = CampaignSyncService(factory, api)
    with patch.object(StreamUnitOfWorkSQLAlchemy, "lock_campaign", lock):
        pushing = asyncio.create_task(
            service.push_stream(draft.id, expected_revision=2)
        )
        await asyncio.wait_for(entered_put.wait(), 5)
        fetching = asyncio.create_task(service.fetch_campaign(367))
        try:
            await asyncio.wait_for(fetch_lock.wait(), 5)
            api.get_campaign_streams.assert_not_called()
        finally:
            release_put.set()
        await asyncio.wait_for(pushing, 5)
        fetched = await asyncio.wait_for(fetching, 5)
    assert [row.share for row in fetched.streams[1].draft.offers] == [25, 38, 37]
    assert not fetched.streams[1].draft.is_dirty
