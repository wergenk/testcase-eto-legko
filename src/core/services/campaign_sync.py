from collections.abc import Callable, Sequence

from pydantic import JsonValue

from src.core.dto import (
    CampaignFetchResultDTO,
    CreateStreamDraftDTO,
    CreateStreamDTO,
    CreateStreamSnapshotDTO,
    DraftOfferDTO,
    FetchedStreamDTO,
    KeitaroOfferDTO,
    KeitaroStreamDTO,
    KeitaroStreamOfferDTO,
    KeitaroStreamOfferInputDTO,
    StreamDraft,
)
from src.core.exceptions import (
    KeitaroError,
    OfferShareError,
    StreamDraftConflictError,
    StreamDraftNotFoundError,
    StreamPublicationConflictError,
    StreamPublicationError,
)
from src.core.interfaces import KeitaroGateway, StreamUnitOfWork


class CampaignSyncService:
    def __init__(
        self,
        uow_factory: Callable[[], StreamUnitOfWork],
        keitaro: KeitaroGateway,
    ) -> None:
        self._uow_factory = uow_factory
        self._keitaro = keitaro

    async def fetch_campaign(
        self, keitaro_campaign_id: int, *, uow: StreamUnitOfWork | None = None
    ) -> CampaignFetchResultDTO:
        """Загрузить кампанию в локальную БД, не меняя Keitaro.

        Запросы выполняются под общей с Push блокировкой кампании, чтобы
        не импортировать устаревший ответ после публикации. Локальные записи
        фиксируются вместе. Неопубликованные изменения любого локального
        потока кампании блокируют Fetch целиком. Параллельная правка черновика
        обнаруживается проверкой revision при сохранении.
        При переданном uow использует его транзакцию без собственного commit.
        """
        if type(keitaro_campaign_id) is not int or keitaro_campaign_id <= 0:
            raise ValueError(
                "ID кампании Keitaro должен быть положительным целым числом"
            )

        if uow is None:
            async with self._uow_factory() as transaction:
                result = await self.fetch_campaign(keitaro_campaign_id, uow=transaction)
                await transaction.commit()
                return result
        await uow.streams.lock_campaign(keitaro_campaign_id)
        # Сначала проверяем всю кампанию, включая пропавшие из API потоки.
        for stream in await uow.streams.list_by_campaign(keitaro_campaign_id):
            draft = await uow.drafts.get_by_stream(stream.id)
            self._ensure_clean(draft)

        remote_streams = await self._keitaro.get_campaign_streams(keitaro_campaign_id)
        self._validate_remote_streams(keitaro_campaign_id, remote_streams)
        catalog = await self._load_offer_catalog(remote_streams)
        fetched = []
        for remote in remote_streams:
            fetched.append(await self._save_stream(uow, remote, catalog))
        return CampaignFetchResultDTO(
            keitaro_campaign_id=keitaro_campaign_id, streams=tuple(fetched)
        )

    async def push_stream(
        self, draft_id: int, *, expected_revision: int
    ) -> StreamDraft:
        """Опубликовать активные офферы и сделать черновик чистым.

        БД не может откатить успешный PUT. После таймаута или сбоя локального
        сохранения повторный Push сравнит удалённый состав с целевым и завершит
        локальную фиксацию без повторного PUT. Это не общая транзакция с Keitaro.
        """
        if type(draft_id) is not int or draft_id <= 0:
            raise ValueError("ID черновика должен быть положительным целым числом")
        if type(expected_revision) is not int or expected_revision <= 0:
            raise ValueError("Версия черновика должна быть положительным целым числом")

        async with self._uow_factory() as uow:
            draft = await uow.drafts.get(draft_id)
            if draft is None:
                raise StreamDraftNotFoundError(f"Черновик {draft_id} не найден")
            stream = await uow.streams.get(draft.stream_id)
            if stream is None:
                raise StreamPublicationError("Не найден локальный поток черновика")
            await uow.streams.lock_campaign(stream.keitaro_campaign_id)
            draft = await uow.drafts.get_for_update(draft_id)
            if draft is None:
                raise StreamDraftNotFoundError(f"Черновик {draft_id} не найден")
            if draft.revision != expected_revision:
                raise StreamDraftConflictError("Версия черновика устарела")
            if not draft.is_dirty:
                return draft

            offers = self._publication_offers(draft)
            snapshot = await uow.snapshots.get(draft.base_snapshot_id)
            if snapshot is None or snapshot.stream_id != draft.stream_id:
                raise StreamPublicationError("Не найден базовый снимок потока")
            remote = await self._keitaro.get_stream(stream.keitaro_stream_id)
            self._validate_publication_stream(
                remote,
                stream.keitaro_stream_id,
                stream.keitaro_campaign_id,
                snapshot.payload,
            )
            baseline = self._snapshot_offer_signature(snapshot.payload)
            current = self._offer_signature(remote.offers)
            target = self._offer_signature(offers)
            if current != target:
                if current != baseline:
                    raise StreamPublicationConflictError(
                        "Офферы изменены в Keitaro после Fetch; публикация отменена"
                    )
                remote = await self._keitaro.replace_stream_offers(
                    stream.keitaro_stream_id, offers
                )
                self._validate_publication_stream(
                    remote,
                    stream.keitaro_stream_id,
                    stream.keitaro_campaign_id,
                    snapshot.payload,
                )
                if self._offer_signature(remote.offers) != target:
                    raise StreamPublicationError(
                        "Keitaro вернул другой состав или доли; проверьте поток "
                        "перед повторным Push"
                    )

            published = await uow.snapshots.create(
                CreateStreamSnapshotDTO(stream_id=stream.id, payload=remote.raw_payload)
            )
            await uow.streams.update(stream.model_copy(update={"name": remote.name}))
            saved = await uow.drafts.update(
                draft.model_copy(
                    update={
                        "base_snapshot_id": published.id,
                        "base_editor_state": draft.offers,
                    }
                ),
                expected_revision=draft.revision,
            )
            if saved is None:
                raise StreamDraftConflictError(
                    "Не удалось зафиксировать результат Push"
                )
            await uow.commit()
            return saved

    @staticmethod
    def _publication_offers(
        draft: StreamDraft,
    ) -> tuple[KeitaroStreamOfferInputDTO, ...]:
        ids = [row.keitaro_offer_id for row in draft.offers]
        if len(set(ids)) != len(ids):
            raise OfferShareError("Офферы черновика не должны повторяться")
        for row in draft.offers:
            if type(row.share) is not int or not 0 <= row.share <= 100:
                raise OfferShareError("Доля должна быть целым числом от 0 до 100")
            if not row.is_active and row.share != 0:
                raise OfferShareError("Доля архивного оффера должна быть нулевой")
        active = sorted(
            (row for row in draft.offers if row.is_active),
            key=lambda row: (row.position, row.keitaro_offer_id),
        )
        if active and sum(row.share for row in active) != 100:
            raise OfferShareError("Сумма активных долей должна быть 100%")
        return tuple(
            KeitaroStreamOfferInputDTO(offer_id=row.keitaro_offer_id, share=row.share)
            for row in active
        )

    @staticmethod
    def _offer_signature(
        offers: Sequence[KeitaroStreamOfferDTO | KeitaroStreamOfferInputDTO],
    ) -> tuple[tuple[int, int, str], ...]:
        return tuple(sorted((row.offer_id, row.share, row.state) for row in offers))

    @classmethod
    def _snapshot_offer_signature(
        cls, payload: dict[str, JsonValue]
    ) -> tuple[tuple[int, int, str], ...]:
        raw = payload.get("offers", [])
        if not isinstance(raw, list) or any(not isinstance(row, dict) for row in raw):
            raise StreamPublicationError(
                "Базовый снимок содержит неверный список офферов"
            )
        try:
            offers = [
                KeitaroStreamOfferDTO(
                    offer_id=row["offer_id"], share=row["share"], state=row["state"]
                )
                for row in raw
            ]
        except (KeyError, ValueError, TypeError):
            raise StreamPublicationError(
                "Повреждены привязки базового снимка"
            ) from None
        if len({row.offer_id for row in offers}) != len(offers):
            raise StreamPublicationError("В базовом снимке повторяются офферы")
        return cls._offer_signature(offers)

    @classmethod
    def _validate_publication_stream(
        cls,
        remote: KeitaroStreamDTO,
        stream_id: int,
        campaign_id: int,
        baseline: dict[str, JsonValue],
    ) -> None:
        if remote.id != stream_id:
            raise StreamPublicationError("Keitaro вернул другой поток")
        cls._validate_remote_streams(campaign_id, [remote])
        schema = remote.raw_payload.get("schema")
        if schema != baseline.get("schema"):
            raise StreamPublicationConflictError("Схема потока изменена после Fetch")
        if schema not in (None, "landings"):
            raise StreamPublicationError(
                "Публиковать офферы можно только в схему лендингов/офферов"
            )

    async def _load_offer_catalog(
        self, streams: Sequence[KeitaroStreamDTO]
    ) -> dict[int, KeitaroOfferDTO]:
        offer_ids = {offer.offer_id for stream in streams for offer in stream.offers}
        if not offer_ids:
            return {}
        catalog = {offer.id: offer for offer in await self._keitaro.list_offers()}
        # Каталог может быть неполным; запрашиваем отсутствующие ID отдельно.
        for offer_id in sorted(offer_ids - catalog.keys()):
            catalog[offer_id] = await self._keitaro.get_offer(offer_id)
        return catalog

    async def _save_stream(
        self,
        uow: StreamUnitOfWork,
        remote: KeitaroStreamDTO,
        catalog: dict[int, KeitaroOfferDTO],
    ) -> FetchedStreamDTO:
        stream = await uow.streams.get_by_keitaro_id(remote.id)
        if stream is None:
            stream = await uow.streams.create(
                CreateStreamDTO(
                    keitaro_stream_id=remote.id,
                    keitaro_campaign_id=remote.campaign_id,
                    name=remote.name,
                )
            )
        elif stream.keitaro_campaign_id != remote.campaign_id:
            raise KeitaroError("Поток уже связан с другой локальной кампанией")
        else:
            stream = stream.model_copy(update={"name": remote.name})
            await uow.streams.update(stream)

        draft = await uow.drafts.get_by_stream(stream.id)
        self._ensure_clean(draft)
        offers = self._merge_offers(remote, draft, catalog)
        snapshot = await uow.snapshots.create(
            CreateStreamSnapshotDTO(stream_id=stream.id, payload=remote.raw_payload)
        )
        if draft is None:
            saved = await uow.drafts.create(
                CreateStreamDraftDTO(
                    stream_id=stream.id,
                    base_snapshot_id=snapshot.id,
                    offers=offers,
                    base_editor_state=offers,
                )
            )
        else:
            saved = await uow.drafts.update(
                draft.model_copy(
                    update={
                        "base_snapshot_id": snapshot.id,
                        "offers": offers,
                        "base_editor_state": offers,
                    }
                ),
                expected_revision=draft.revision,
            )
            if saved is None:
                raise StreamDraftConflictError("Черновик изменился во время Fetch")
        return FetchedStreamDTO(stream=stream, draft=saved)

    @staticmethod
    def _ensure_clean(draft: StreamDraft | None) -> None:
        if draft is not None and draft.is_dirty:
            raise StreamDraftConflictError(
                f"В потоке {draft.stream_id} есть неопубликованные изменения. "
                "Перед Fetch выполните Cancel или Push"
            )

    @staticmethod
    def _merge_offers(
        remote: KeitaroStreamDTO,
        draft: StreamDraft | None,
        catalog: dict[int, KeitaroOfferDTO],
    ) -> tuple[DraftOfferDTO, ...]:
        previous = (
            {}
            if draft is None
            else {offer.keitaro_offer_id: offer for offer in draft.offers}
        )
        current = []
        for position, link in enumerate(remote.offers):
            old = previous.get(link.offer_id)
            active = link.state == "active"
            current.append(
                DraftOfferDTO(
                    keitaro_offer_id=link.offer_id,
                    name=catalog[link.offer_id].name,
                    share=link.share if active else 0,
                    is_pinned=bool(active and old and old.is_active and old.is_pinned),
                    is_active=active,
                    position=position,
                )
            )
        present = {offer.offer_id for offer in remote.offers}
        for old in sorted(
            previous.values(), key=lambda row: (row.position, row.keitaro_offer_id)
        ):
            if old.keitaro_offer_id not in present:
                current.append(
                    old.model_copy(
                        update={
                            "share": 0,
                            "is_active": False,
                            "is_pinned": False,
                            "position": len(current),
                        }
                    )
                )
        return tuple(current)

    @staticmethod
    def _validate_remote_streams(
        campaign_id: int, streams: Sequence[KeitaroStreamDTO]
    ) -> None:
        seen = set()
        for stream in streams:
            if stream.campaign_id != campaign_id or stream.id in seen:
                raise KeitaroError(
                    "API вернул неверный или повторяющийся поток кампании"
                )
            seen.add(stream.id)
            offer_ids = [offer.offer_id for offer in stream.offers]
            if len(set(offer_ids)) != len(offer_ids):
                raise KeitaroError("API вернул повторяющиеся офферы потока")
