from src.core.dto import DraftOfferDTO, StreamDraft
from src.core.exceptions import (
    DraftOfferError,
    OfferShareError,
    StreamDraftConflictError,
    StreamDraftNotFoundError,
)
from src.core.interfaces import KeitaroGateway
from src.core.interfaces.repositories import StreamDraftRepository

from .offer_share import recalculate_offer_shares


class StreamDraftService:
    """Редактор локального черновика; не публикует изменения в Keitaro.

    Вызывающий код управляет транзакцией репозитория. expected_revision —
    версия, которую видел клиент. Она проверяется при загрузке и атомарном
    сохранении. Ошибки не должны приводить к коммиту транзакции.
    """

    def __init__(
        self,
        drafts: StreamDraftRepository,
        keitaro: KeitaroGateway,
    ) -> None:
        self._drafts = drafts
        self._keitaro = keitaro

    async def add_offer(
        self, draft_id: int, offer_id: int, *, expected_revision: int
    ) -> StreamDraft:
        draft = await self._get_draft(draft_id, expected_revision)
        if any(offer.keitaro_offer_id == offer_id for offer in draft.offers):
            raise DraftOfferError(
                "Оффер уже есть в черновике; архивный нужно восстановить"
            )

        remote = await self._keitaro.get_offer(offer_id)
        if remote.state != "active":
            raise DraftOfferError("Добавить можно только активный оффер Keitaro")

        offer = DraftOfferDTO(
            keitaro_offer_id=remote.id,
            name=remote.name,
            share=0,
            is_pinned=False,
            is_active=True,
            position=max((row.position for row in draft.offers), default=-1) + 1,
        )
        offers = recalculate_offer_shares((*draft.offers, offer))
        return await self._save(draft, offers)

    async def remove_offer(
        self, draft_id: int, offer_id: int, *, expected_revision: int
    ) -> StreamDraft:
        draft = await self._get_draft(draft_id, expected_revision)
        offer = self._find_offer(draft, offer_id)
        if not offer.is_active:
            return draft

        # Удаление освобождает закреплённую долю; Restore распределит её заново.
        removed = offer.model_copy(
            update={"is_active": False, "is_pinned": False, "share": 0}
        )
        offers = recalculate_offer_shares(self._replace_offer(draft, removed))
        return await self._save(draft, offers)

    async def restore_offer(
        self, draft_id: int, offer_id: int, *, expected_revision: int
    ) -> StreamDraft:
        draft = await self._get_draft(draft_id, expected_revision)
        offer = self._find_offer(draft, offer_id)
        if offer.is_active:
            return draft

        remote = await self._keitaro.get_offer(offer_id)
        if remote.state != "active":
            raise DraftOfferError("Восстановить можно только активный оффер Keitaro")

        restored = offer.model_copy(
            update={"is_active": True, "is_pinned": False, "name": remote.name}
        )
        offers = recalculate_offer_shares(self._replace_offer(draft, restored))
        return await self._save(draft, offers)

    async def pin_share(
        self,
        draft_id: int,
        offer_id: int,
        share: int,
        *,
        expected_revision: int,
    ) -> StreamDraft:
        draft = await self._get_draft(draft_id, expected_revision)
        offer = self._find_offer(draft, offer_id)
        if not offer.is_active:
            raise DraftOfferError("Нельзя закрепить долю архивного оффера")
        if type(share) is not int or not 0 <= share <= 100:
            raise OfferShareError("Доля должна быть целым числом от 0 до 100")

        pinned = offer.model_copy(update={"is_pinned": True, "share": share})
        offers = recalculate_offer_shares(self._replace_offer(draft, pinned))
        return await self._save(draft, offers)

    async def unpin_share(
        self, draft_id: int, offer_id: int, *, expected_revision: int
    ) -> StreamDraft:
        draft = await self._get_draft(draft_id, expected_revision)
        offer = self._find_offer(draft, offer_id)
        if not offer.is_active:
            raise DraftOfferError("Нельзя изменить долю архивного оффера")
        if not offer.is_pinned:
            return draft

        unpinned = offer.model_copy(update={"is_pinned": False})
        offers = recalculate_offer_shares(self._replace_offer(draft, unpinned))
        return await self._save(draft, offers)

    async def cancel_changes(
        self, draft_id: int, *, expected_revision: int
    ) -> StreamDraft:
        """Вернуть базовый состав, доли, архив и закрепления без пересчёта."""
        draft = await self._get_draft(draft_id, expected_revision)
        return await self._save(draft, draft.base_editor_state)

    async def _get_draft(self, draft_id: int, expected_revision: int) -> StreamDraft:
        draft = await self._drafts.get(draft_id)
        if draft is None:
            raise StreamDraftNotFoundError(f"Черновик {draft_id} не найден")
        if draft.revision != expected_revision:
            raise StreamDraftConflictError("Версия черновика устарела; обновите данные")
        return draft

    @staticmethod
    def _find_offer(draft: StreamDraft, offer_id: int) -> DraftOfferDTO:
        for offer in draft.offers:
            if offer.keitaro_offer_id == offer_id:
                return offer
        raise DraftOfferError(f"Оффер {offer_id} отсутствует в черновике")

    @staticmethod
    def _replace_offer(
        draft: StreamDraft, updated: DraftOfferDTO
    ) -> tuple[DraftOfferDTO, ...]:
        return tuple(
            updated if offer.keitaro_offer_id == updated.keitaro_offer_id else offer
            for offer in draft.offers
        )

    async def _save(
        self, draft: StreamDraft, offers: tuple[DraftOfferDTO, ...]
    ) -> StreamDraft:
        if offers == draft.offers:
            return draft
        updated = await self._drafts.update(
            draft.model_copy(update={"offers": offers}),
            expected_revision=draft.revision,
        )
        if updated is None:
            raise StreamDraftConflictError("Черновик изменился во время сохранения")
        return updated
