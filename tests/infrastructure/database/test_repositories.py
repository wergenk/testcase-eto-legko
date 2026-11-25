import asyncio
from datetime import UTC, datetime
from unittest.mock import create_autospec

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from src.core.dto import (
    CreateStreamDraftDTO,
    CreateStreamDTO,
    CreateStreamSnapshotDTO,
    DraftOfferDTO,
    StreamDraft,
)
from src.core.interfaces import KeitaroGateway, StreamUnitOfWork
from src.core.services import StreamDraftService
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy

pytestmark = pytest.mark.asyncio


def row(offer_id: int, *, active: bool = True, position: int = 0) -> DraftOfferDTO:
    return DraftOfferDTO(
        keitaro_offer_id=offer_id,
        name=f"Offer {offer_id}",
        share=50 if active else 0,
        is_active=active,
        is_pinned=False,
        position=position,
    )


async def seed(uow: StreamUnitOfWork) -> StreamDraft:
    stream = await uow.streams.create(
        CreateStreamDTO(keitaro_stream_id=100, keitaro_campaign_id=5, name="Original")
    )
    snapshot = await uow.snapshots.create(
        CreateStreamSnapshotDTO(stream_id=stream.id, payload={"offers": []})
    )
    offers = (row(10), row(20, active=False, position=1), row(12, position=2))
    return await uow.drafts.create(
        CreateStreamDraftDTO(
            stream_id=stream.id,
            base_snapshot_id=snapshot.id,
            offers=offers,
            base_editor_state=offers,
        )
    )


async def test_stream_crud_and_identity(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        first = await uow.streams.create(
            CreateStreamDTO(keitaro_stream_id=9, keitaro_campaign_id=5, name="A")
        )
        second = await uow.streams.create(
            CreateStreamDTO(keitaro_stream_id=8, keitaro_campaign_id=5, name="B")
        )
        assert await uow.streams.get(first.id) == first
        assert await uow.streams.get_by_keitaro_id(9) == first
        assert await uow.streams.list_by_campaign(5) == [first, second]
        assert await uow.streams.list_by_campaign(999) == []
        assert await uow.streams.get(999) is None
        assert await uow.streams.get_by_keitaro_id(999) is None
        await uow.streams.update(first.model_copy(update={"name": "Renamed"}))
        changed = await uow.streams.get(first.id)
        assert changed is not None and changed.name == "Renamed"
        assert changed.created_at == first.created_at
        with pytest.raises(ValueError):
            await uow.streams.update(first.model_copy(update={"keitaro_stream_id": 99}))
        with pytest.raises(ValueError):
            await uow.streams.update(first.model_copy(update={"id": 999}))
        await uow.commit()


async def test_snapshot_latest_breaks_timestamp_tie_and_json_is_detached(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        payload = {"offers": [{"offer_id": 77}], "filters": ["AU"]}
        snapshot = await uow.snapshots.create(
            CreateStreamSnapshotDTO(stream_id=draft.stream_id, payload=payload)
        )
        original = await uow.snapshots.get(draft.base_snapshot_id)
        assert original is not None
        assert (
            snapshot.created_at == original.created_at
        )  # PostgreSQL now(): начало tx.
        assert await uow.snapshots.get_latest(draft.stream_id) == snapshot
        payload["filters"].append("US")
        snapshot.payload["filters"].append("GB")
        reloaded = await uow.snapshots.get(snapshot.id)
        assert reloaded is not None and reloaded.payload["filters"] == ["AU"]
        assert await uow.snapshots.get(999) is None
        assert await uow.snapshots.get_latest(999) is None


async def test_draft_round_trip_archive_order_and_empty_offers(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        assert await uow.drafts.get(draft.id) == draft
        assert await uow.drafts.get_by_stream(draft.stream_id) == draft
        assert await uow.drafts.get(999) is None
        assert await uow.drafts.get_by_stream(999) is None
        unsorted = (row(12, position=2), row(20, active=False), row(10))
        updated = await uow.drafts.update(
            draft.model_copy(update={"offers": unsorted}), expected_revision=1
        )
        assert updated is not None
        assert [offer.keitaro_offer_id for offer in updated.offers] == [10, 20, 12]
        assert not updated.offers[1].is_active
        assert await uow.drafts.get(draft.id) == updated
        empty = await uow.drafts.update(
            updated.model_copy(update={"offers": ()}), expected_revision=2
        )
        assert empty is not None and empty.offers == ()
        assert await uow.drafts.get(draft.id) == empty
        assert empty.base_editor_state == draft.base_editor_state


async def test_draft_update_rebases_and_uses_database_revision_and_timestamps(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        snapshot = await uow.snapshots.create(
            CreateStreamSnapshotDTO(stream_id=draft.stream_id, payload={"offers": [33]})
        )
        baseline = (row(33),)
        changed = draft.model_copy(
            update={
                "offers": baseline,
                "base_editor_state": baseline,
                "base_snapshot_id": snapshot.id,
                "revision": 999,
                "created_at": datetime(2000, 1, 1, tzinfo=UTC),
            }
        )
        updated = await uow.drafts.update(changed, expected_revision=1)
        assert updated is not None and updated.revision == 2
        assert updated.created_at == draft.created_at
        assert updated.updated_at >= draft.updated_at
        assert updated.base_snapshot_id == snapshot.id
        assert updated.base_editor_state == baseline
        assert await uow.drafts.get(draft.id) == updated


@pytest.mark.parametrize("changes", [{"revision": 99}, {"id": 999}, {"stream_id": 999}])
async def test_failed_cas_does_not_change_header_or_offers(
    manager: AsyncDatabaseSessionManager,
    changes: dict[str, int],
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        expected_revision = changes.get("revision", draft.revision)
        changed = draft.model_copy(update={**changes, "offers": ()})
        assert (
            await uow.drafts.update(changed, expected_revision=expected_revision)
            is None
        )
        assert await uow.drafts.get(draft.id) == draft


async def test_duplicate_offer_update_is_atomic_even_when_error_is_caught(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        invalid = draft.model_copy(update={"offers": (row(99), row(99))})
        with pytest.raises(IntegrityError):
            await uow.drafts.update(invalid, expected_revision=1)
        assert await uow.drafts.get(draft.id) == draft
        await uow.commit()
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        assert await uow.drafts.get(draft.id) == draft


async def test_failed_create_leaves_no_draft_and_transaction_can_continue(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        stream = await uow.streams.create(
            CreateStreamDTO(keitaro_stream_id=1, keitaro_campaign_id=1, name="A")
        )
        snapshot = await uow.snapshots.create(
            CreateStreamSnapshotDTO(stream_id=stream.id, payload={})
        )
        data = CreateStreamDraftDTO(
            stream_id=stream.id,
            base_snapshot_id=snapshot.id,
            offers=(row(99), row(99)),
            base_editor_state=(),
        )
        with pytest.raises(IntegrityError):
            await uow.drafts.create(data)
        assert await uow.drafts.get_by_stream(stream.id) is None
        created = await uow.drafts.create(data.model_copy(update={"offers": ()}))
        assert created.revision == 1 and created.offers == ()
        await uow.commit()


async def test_foreign_snapshot_update_is_atomic(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        other = await uow.streams.create(
            CreateStreamDTO(keitaro_stream_id=200, keitaro_campaign_id=5, name="Other")
        )
        snapshot = await uow.snapshots.create(
            CreateStreamSnapshotDTO(stream_id=other.id, payload={})
        )
        with pytest.raises(IntegrityError):
            await uow.drafts.update(
                draft.model_copy(
                    update={"base_snapshot_id": snapshot.id, "offers": ()}
                ),
                expected_revision=1,
            )
        assert await uow.drafts.get(draft.id) == draft


async def test_commit_is_shared_by_all_repositories_and_not_automatic(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as writer:
        draft = await seed(writer)
        async with StreamUnitOfWorkSQLAlchemy(manager) as reader:
            assert await reader.drafts.get(draft.id) is None
            assert await reader.streams.get(draft.stream_id) is None
            assert await reader.snapshots.get(draft.base_snapshot_id) is None
        await writer.commit()
    async with StreamUnitOfWorkSQLAlchemy(manager) as reader:
        assert await reader.drafts.get(draft.id) == draft
        assert await reader.streams.get(draft.stream_id) is not None
        assert await reader.snapshots.get(draft.base_snapshot_id) is not None


@pytest.mark.parametrize("fail", [False, True])
async def test_exit_without_commit_rolls_back_all_repositories(
    manager: AsyncDatabaseSessionManager,
    fail: bool,
) -> None:
    async def write() -> StreamDraft:
        async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
            draft = await seed(uow)
            if fail:
                raise RuntimeError("Abort")
            return draft

    if fail:
        with pytest.raises(RuntimeError, match="Abort"):
            await write()
    else:
        await write()
    async with StreamUnitOfWorkSQLAlchemy(manager) as reader:
        assert await reader.streams.get_by_keitaro_id(100) is None
        assert await reader.drafts.get(1) is None
        assert await reader.snapshots.get(1) is None


async def test_manual_rollback_and_work_after_commit(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        await seed(uow)
        await uow.rollback()
        assert await uow.streams.get_by_keitaro_id(100) is None
        committed = await seed(uow)
        await uow.commit()
        await uow.streams.create(
            CreateStreamDTO(
                keitaro_stream_id=999, keitaro_campaign_id=5, name="Pending"
            )
        )
    async with StreamUnitOfWorkSQLAlchemy(manager) as reader:
        assert await reader.drafts.get(committed.id) == committed
        assert await reader.streams.get_by_keitaro_id(999) is None


async def test_uow_lifecycle_nested_entry_and_stale_repository(
    manager: AsyncDatabaseSessionManager,
) -> None:
    uow = StreamUnitOfWorkSQLAlchemy(manager)
    with pytest.raises(RuntimeError):
        _ = uow.streams
    with pytest.raises(RuntimeError):
        await uow.commit()
    with pytest.raises(RuntimeError):
        await uow.rollback()
    async with uow:
        captured = uow.streams
        with pytest.raises(RuntimeError, match="уже открыт"):
            async with uow:
                pass
        await seed(uow)
    with pytest.raises(RuntimeError):
        _ = uow.drafts
    with pytest.raises(InvalidRequestError):
        await captured.get(1)
    async with uow:
        assert await uow.streams.get_by_keitaro_id(100) is None


async def test_two_concurrent_writers_have_exactly_one_winner(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        await uow.commit()
    barrier = asyncio.Barrier(2)

    async def write(offer_id: int) -> StreamDraft | None:
        async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
            current = await uow.drafts.get(draft.id)
            assert current is not None and current.revision == 1
            await barrier.wait()
            result = await uow.drafts.update(
                current.model_copy(update={"offers": (row(offer_id),)}),
                expected_revision=1,
            )
            await uow.commit()
            return result

    results = await asyncio.wait_for(asyncio.gather(write(77), write(88)), timeout=10)
    winners = [result for result in results if result is not None]
    assert len(winners) == 1 and winners[0].revision == 2
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        assert await uow.drafts.get(draft.id) == winners[0]


async def test_editor_service_uses_real_repository_and_uow(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        draft = await seed(uow)
        await uow.commit()
    gateway = create_autospec(KeitaroGateway, instance=True)
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        service = StreamDraftService(uow.drafts, gateway)
        removed = await service.remove_offer(draft.id, 10, expected_revision=1)
        assert [offer.share for offer in removed.offers] == [0, 0, 100]
        await uow.commit()
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        assert await uow.drafts.get(draft.id) == removed
        service = StreamDraftService(uow.drafts, gateway)
        cancelled = await service.cancel_changes(draft.id, expected_revision=2)
        await uow.commit()
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        saved = await uow.drafts.get(draft.id)
        assert saved == cancelled
        assert saved.offers == draft.offers
        assert saved.revision == 3
    gateway.replace_stream_offers.assert_not_called()


async def test_manager_closes_session_without_implicit_commit(
    manager: AsyncDatabaseSessionManager,
) -> None:
    async with manager.session() as session:
        await session.execute(
            text(
                "INSERT INTO streams "
                "(keitaro_stream_id, keitaro_campaign_id, name) "
                "VALUES (999, 5, 'Pending')"
            )
        )
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        assert await uow.streams.get_by_keitaro_id(999) is None
