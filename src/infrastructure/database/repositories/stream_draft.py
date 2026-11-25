from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.elements import ColumnElement

from src.core.dto import CreateStreamDraftDTO, DraftOfferDTO, StreamDraft
from src.core.interfaces.repositories import StreamDraftRepository
from src.infrastructure.database.models import DraftOfferORM, StreamDraftORM

from .base import BaseRepository


class StreamDraftSQLAlchemyRepository(BaseRepository, StreamDraftRepository):
    async def _get_orm(
        self, condition: ColumnElement[bool], *, for_update: bool = False
    ) -> StreamDraftORM | None:
        stmt = (
            select(StreamDraftORM)
            .options(joinedload(StreamDraftORM.offers))
            .where(condition)
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update(of=StreamDraftORM)
        return (await self.session.execute(stmt)).unique().scalars().one_or_none()

    async def create(self, data: CreateStreamDraftDTO) -> StreamDraft:
        async with self.session.begin_nested():
            draft_orm = StreamDraftORM(
                stream_id=data.stream_id,
                base_snapshot_id=data.base_snapshot_id,
                base_editor_state=[
                    offer.model_dump(mode="json") for offer in data.base_editor_state
                ],
                offers=self._create_offer_models(data.offers),
            )
            self.session.add(draft_orm)
            await self.session.flush()
            return self._validate(StreamDraft, draft_orm)

    async def get(self, draft_id: int) -> StreamDraft | None:
        draft_orm = await self._get_orm(StreamDraftORM.id == draft_id)
        return self._validate(StreamDraft, draft_orm)

    async def get_for_update(self, draft_id: int) -> StreamDraft | None:
        draft_orm = await self._get_orm(StreamDraftORM.id == draft_id, for_update=True)
        return self._validate(StreamDraft, draft_orm)

    async def get_by_stream(self, stream_id: int) -> StreamDraft | None:
        draft_orm = await self._get_orm(StreamDraftORM.stream_id == stream_id)
        return self._validate(StreamDraft, draft_orm)

    async def update(
        self, draft: StreamDraft, *, expected_revision: int
    ) -> StreamDraft | None:
        async with self.session.begin_nested():
            # Проверка версии и блокировка строки выполняются одним UPDATE.
            stmt = (
                update(StreamDraftORM)
                .where(
                    StreamDraftORM.id == draft.id,
                    StreamDraftORM.stream_id == draft.stream_id,
                    StreamDraftORM.revision == expected_revision,
                )
                .values(
                    base_snapshot_id=draft.base_snapshot_id,
                    base_editor_state=[
                        offer.model_dump(mode="json")
                        for offer in draft.base_editor_state
                    ],
                    revision=expected_revision + 1,
                    updated_at=func.clock_timestamp(),
                )
                .returning(StreamDraftORM)
                .execution_options(populate_existing=True)
            )
            draft_orm = (await self.session.execute(stmt)).scalars().one_or_none()
            if draft_orm is None:
                return None

            # После успешного CAS строка заблокирована до завершения транзакции.
            await self.session.refresh(draft_orm, attribute_names=["offers"])
            draft_orm.offers.clear()
            # Сначала удаляем старые строки, освобождая уникальные ключи.
            await self.session.flush()
            draft_orm.offers = self._create_offer_models(draft.offers)
            await self.session.flush()
            return self._validate(StreamDraft, draft_orm)

    @staticmethod
    def _create_offer_models(offers: Sequence[DraftOfferDTO]) -> list[DraftOfferORM]:
        return [
            DraftOfferORM(**offer.model_dump())
            for offer in sorted(
                offers, key=lambda offer: (offer.position, offer.keitaro_offer_id)
            )
        ]
