from datetime import UTC, datetime
from unittest.mock import Mock, create_autospec

import pytest

from src.core.dto import CreateStreamDraftDTO, DraftOfferDTO, StreamDraft
from src.core.dto.keitaro import KeitaroOfferDTO
from src.core.exceptions import (
    DraftOfferError,
    KeitaroNotFoundError,
    OfferShareError,
    StreamDraftConflictError,
    StreamDraftNotFoundError,
)
from src.core.interfaces import KeitaroGateway, StreamUnitOfWork
from src.core.interfaces.repositories import StreamDraftRepository
from src.core.services import StreamDraftService

pytestmark = pytest.mark.asyncio


def offer(
    offer_id: int, share: int, *, pinned: bool = False, active: bool = True
) -> DraftOfferDTO:
    return DraftOfferDTO(
        keitaro_offer_id=offer_id,
        name=f"Offer {offer_id}",
        share=share,
        is_pinned=pinned,
        is_active=active,
        position=offer_id,
    )


class MemoryDraftRepository(StreamDraftRepository):
    def __init__(self, draft: StreamDraft) -> None:
        self.draft: StreamDraft | None = draft
        self.updates = 0
        self.conflict = False

    async def create(self, data: CreateStreamDraftDTO) -> StreamDraft:
        raise NotImplementedError

    async def get(self, draft_id: int) -> StreamDraft | None:
        if self.draft is not None and self.draft.id == draft_id:
            return self.draft.model_copy(deep=True)
        return None

    async def get_for_update(self, draft_id: int) -> StreamDraft | None:
        return await self.get(draft_id)

    async def get_by_stream(self, stream_id: int) -> StreamDraft | None:
        if self.draft is not None and self.draft.stream_id == stream_id:
            return self.draft.model_copy(deep=True)
        return None

    async def update(
        self, draft: StreamDraft, *, expected_revision: int
    ) -> StreamDraft | None:
        if self.conflict or self.draft is None:
            return None
        if self.draft.revision != expected_revision:
            return None
        self.updates += 1
        self.draft = draft.model_copy(
            update={"revision": expected_revision + 1, "updated_at": datetime.now(UTC)},
            deep=True,
        )
        return self.draft.model_copy(deep=True)


@pytest.fixture
def uow() -> Mock:
    transaction = create_autospec(StreamUnitOfWork, instance=True)
    transaction.__aenter__.return_value = transaction
    transaction.__aexit__.return_value = False
    return transaction


@pytest.fixture
def editor(uow: Mock) -> tuple[StreamDraftService, MemoryDraftRepository, Mock]:
    now = datetime.now(UTC)
    baseline = (offer(1, 25, pinned=True), offer(2, 75), offer(3, 0, active=False))
    draft = StreamDraft(
        id=1,
        stream_id=1,
        base_snapshot_id=1,
        revision=1,
        offers=baseline,
        base_editor_state=baseline,
        created_at=now,
        updated_at=now,
    )
    repository = MemoryDraftRepository(draft)
    uow.drafts = repository
    gateway = create_autospec(KeitaroGateway, instance=True, spec_set=True)
    gateway.get_offer.side_effect = lambda offer_id: KeitaroOfferDTO(
        id=offer_id, name=f"Offer {offer_id}", state="active"
    )
    return (
        StreamDraftService(Mock(return_value=uow), gateway),
        repository,
        gateway,
    )


async def test_add_checks_keitaro_and_preserves_archive_and_baseline(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, repository, gateway = editor
    original = await repository.get(1)

    result = await service.add_offer(1, 4, expected_revision=1)

    assert [row.share for row in result.offers] == [25, 38, 0, 37]
    assert result.revision == 2
    assert original is not None
    assert result.base_editor_state == original.offers
    assert result.base_snapshot_id == original.base_snapshot_id
    gateway.get_offer.assert_awaited_once_with(4)
    gateway.replace_stream_offers.assert_not_called()


async def test_remove_archives_and_restore_redistributes_without_duplicate(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, _, _ = editor
    await service.add_offer(1, 4, expected_revision=1)
    removed = await service.remove_offer(1, 2, expected_revision=2)
    restored = await service.restore_offer(1, 2, expected_revision=3)

    assert [row.share for row in removed.offers] == [25, 0, 0, 75]
    assert not removed.offers[1].is_active
    assert [row.share for row in restored.offers] == [25, 38, 0, 37]
    assert len(restored.offers) == 4


async def test_remove_releases_pin_and_cancel_restores_it(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, _, _ = editor
    removed = await service.remove_offer(1, 1, expected_revision=1)
    cancelled = await service.cancel_changes(1, expected_revision=2)

    assert removed.offers[0].share == 0
    assert not removed.offers[0].is_pinned
    assert removed.offers[1].share == 100
    assert cancelled.offers == cancelled.base_editor_state
    assert cancelled.offers[0].is_pinned
    assert cancelled.offers[0].share == 25


async def test_restore_previously_archived_offer(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, _, _ = editor
    restored = await service.restore_offer(1, 3, expected_revision=1)

    assert [row.share for row in restored.offers] == [25, 38, 37]
    assert restored.offers[2].is_active


async def test_pin_and_unpin_recalculate_other_shares(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, _, _ = editor
    pinned = await service.pin_share(1, 1, 40, expected_revision=1)
    unpinned = await service.unpin_share(1, 1, expected_revision=2)

    assert [row.share for row in pinned.offers] == [40, 60, 0]
    assert [row.share for row in unpinned.offers] == [50, 50, 0]
    assert not unpinned.offers[0].is_pinned


async def test_cancel_drops_new_rows_and_restores_archive_and_exact_shares(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, _, _ = editor
    await service.add_offer(1, 4, expected_revision=1)
    await service.restore_offer(1, 3, expected_revision=2)
    result = await service.cancel_changes(1, expected_revision=3)

    assert result.offers == result.base_editor_state
    assert [row.keitaro_offer_id for row in result.offers] == [1, 2, 3]
    assert not result.offers[2].is_active
    assert result.revision == 4


async def test_noops_do_not_bump_revision_or_call_keitaro(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
    uow: Mock,
) -> None:
    service, repository, gateway = editor
    assert (await service.remove_offer(1, 3, expected_revision=1)).revision == 1
    assert (await service.restore_offer(1, 1, expected_revision=1)).revision == 1
    assert (await service.unpin_share(1, 2, expected_revision=1)).revision == 1
    assert (await service.cancel_changes(1, expected_revision=1)).revision == 1
    assert repository.updates == 0
    gateway.get_offer.assert_not_called()
    uow.commit.assert_not_awaited()


@pytest.mark.parametrize("offer_id", [1, 3])
async def test_duplicate_including_archive_is_rejected(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
    offer_id: int,
) -> None:
    service, repository, gateway = editor
    with pytest.raises(DraftOfferError):
        await service.add_offer(1, offer_id, expected_revision=1)
    assert repository.updates == 0
    gateway.get_offer.assert_not_called()


async def test_missing_draft_and_offer(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, repository, _ = editor
    with pytest.raises(StreamDraftNotFoundError):
        await service.remove_offer(999, 1, expected_revision=1)
    with pytest.raises(DraftOfferError):
        await service.remove_offer(1, 999, expected_revision=1)
    assert repository.updates == 0


async def test_stale_client_is_rejected_before_remote_request(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
    uow: Mock,
) -> None:
    service, repository, gateway = editor
    with pytest.raises(StreamDraftConflictError):
        await service.add_offer(1, 4, expected_revision=99)
    assert repository.updates == 0
    gateway.get_offer.assert_not_called()
    uow.commit.assert_not_awaited()


async def test_race_during_save_does_not_overwrite_draft(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
    uow: Mock,
) -> None:
    service, repository, _ = editor
    original = await repository.get(1)
    repository.conflict = True
    with pytest.raises(StreamDraftConflictError):
        await service.remove_offer(1, 1, expected_revision=1)
    assert await repository.get(1) == original
    uow.commit.assert_not_awaited()


@pytest.mark.parametrize("share", [-1, 101, True, 25.5, "25"])
async def test_invalid_pin_does_not_save(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
    share: object,
) -> None:
    service, repository, _ = editor
    with pytest.raises(OfferShareError):
        await service.pin_share(1, 1, share, expected_revision=1)
    assert repository.updates == 0


async def test_impossible_pinned_sum_does_not_save(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, repository, _ = editor
    with pytest.raises(OfferShareError):
        await service.pin_share(1, 2, 90, expected_revision=1)
    with pytest.raises(OfferShareError):
        await service.pin_share(1, 2, 50, expected_revision=1)
    assert repository.updates == 0


async def test_cannot_change_archive_pin(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, repository, _ = editor
    with pytest.raises(DraftOfferError):
        await service.pin_share(1, 3, 20, expected_revision=1)
    with pytest.raises(DraftOfferError):
        await service.unpin_share(1, 3, expected_revision=1)
    assert repository.updates == 0


async def test_keitaro_missing_or_inactive_offer_does_not_save(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, repository, gateway = editor
    gateway.get_offer.side_effect = KeitaroNotFoundError()
    with pytest.raises(KeitaroNotFoundError):
        await service.add_offer(1, 4, expected_revision=1)
    gateway.get_offer.side_effect = None
    gateway.get_offer.return_value = KeitaroOfferDTO(
        id=4, name="Deleted", state="deleted"
    )
    with pytest.raises(DraftOfferError):
        await service.add_offer(1, 4, expected_revision=1)
    with pytest.raises(DraftOfferError):
        await service.restore_offer(1, 3, expected_revision=1)
    assert repository.updates == 0


async def test_removing_last_active_offer_is_allowed(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
) -> None:
    service, _, _ = editor
    await service.remove_offer(1, 1, expected_revision=1)
    result = await service.remove_offer(1, 2, expected_revision=2)
    assert all(not row.is_active and row.share == 0 for row in result.offers)


@pytest.mark.parametrize(
    "method,args",
    [
        ("add_offer", (1, 4)),
        ("remove_offer", (1, 1)),
        ("restore_offer", (1, 3)),
        ("pin_share", (1, 1, 40)),
        ("unpin_share", (1, 1)),
        ("cancel_changes", (1,)),
    ],
)
async def test_mutation_owns_transaction_and_commits_once(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock],
    uow: Mock,
    method: str,
    args: tuple[int, ...],
) -> None:
    service, repository, _ = editor
    if method == "cancel_changes":
        repository.draft = repository.draft.model_copy(update={"offers": ()})

    result = await getattr(service, method)(*args, expected_revision=1)

    assert result.revision == 2
    uow.__aenter__.assert_awaited_once()
    uow.commit.assert_awaited_once()
    uow.__aexit__.assert_awaited_once_with(None, None, None)


async def test_commit_failure_is_propagated_and_uow_is_closed(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock], uow: Mock
) -> None:
    service, _, _ = editor
    uow.commit.side_effect = RuntimeError("Commit failed")

    with pytest.raises(RuntimeError, match="Commit failed"):
        await service.remove_offer(1, 1, expected_revision=1)

    uow.commit.assert_awaited_once()
    assert uow.__aexit__.await_args.args[0] is RuntimeError


async def test_upstream_failure_exits_uow_without_commit(
    editor: tuple[StreamDraftService, MemoryDraftRepository, Mock], uow: Mock
) -> None:
    service, _, gateway = editor
    gateway.get_offer.side_effect = KeitaroNotFoundError("Missing offer")

    with pytest.raises(KeitaroNotFoundError):
        await service.add_offer(1, 4, expected_revision=1)

    uow.commit.assert_not_awaited()
    assert uow.__aexit__.await_args.args[0] is KeitaroNotFoundError
