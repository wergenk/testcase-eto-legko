from collections.abc import Sequence

from src.core.dto import DraftOfferDTO
from src.core.exceptions import OfferShareError


def recalculate_offer_shares(
    offers: Sequence[DraftOfferDTO],
) -> tuple[DraftOfferDTO, ...]:
    """Пересчитать целые доли, сохранив закрепления активных офферов.

    Архив получает 0%. Остаток распределяется поровну между активными
    незакреплёнными строками; лишний процент получают первые строки
    по (position, keitaro_offer_id). Порядок результата совпадает с входом.
    Если активных строк нет, возвращается архив с нулевыми долями.
    Исходные DTO не изменяются.

    Raises:
        OfferShareError: ID повторяются, сумма закреплённых долей больше
            100% либо все активные доли закреплены и их сумма не 100%.
    """
    offer_ids = [offer.keitaro_offer_id for offer in offers]
    if len(set(offer_ids)) != len(offer_ids):
        raise OfferShareError("Оффер не может повторяться в одном потоке")

    active = [offer for offer in offers if offer.is_active]
    pinned_total = sum(offer.share for offer in active if offer.is_pinned)
    if pinned_total > 100:
        raise OfferShareError("Сумма закреплённых долей превышает 100%")

    unpinned = sorted(
        (offer for offer in active if not offer.is_pinned),
        key=lambda offer: (offer.position, offer.keitaro_offer_id),
    )
    if active and not unpinned and pinned_total != 100:
        raise OfferShareError("Все активные доли закреплены, но их сумма не равна 100%")

    shares: dict[int, int] = {}
    if unpinned:
        base_share, remainder = divmod(100 - pinned_total, len(unpinned))
        shares = {
            offer.keitaro_offer_id: base_share + int(index < remainder)
            for index, offer in enumerate(unpinned)
        }

    result = []
    for offer in offers:
        share = 0
        if offer.is_active:
            share = offer.share if offer.is_pinned else shares[offer.keitaro_offer_id]
        result.append(offer.model_copy(update={"share": share}))

    return tuple(result)
