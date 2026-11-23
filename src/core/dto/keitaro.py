from typing import Annotated, Literal

from pydantic import Field, JsonValue

from .base import FrozenBaseDTO

KeitaroID = Annotated[int, Field(strict=True, gt=0)]
OfferShare = Annotated[int, Field(strict=True, ge=0, le=100)]


class KeitaroOfferDTO(FrozenBaseDTO):
    """Оффер из каталога Keitaro; не содержит локальных настроек редактора."""

    id: KeitaroID
    name: str
    state: str


class KeitaroStreamOfferDTO(FrozenBaseDTO):
    """Привязка оффера, прочитанная из потока Keitaro."""

    offer_id: KeitaroID
    share: OfferShare
    state: str


class KeitaroStreamDTO(FrozenBaseDTO):
    id: KeitaroID
    campaign_id: KeitaroID
    name: str
    offers: tuple[KeitaroStreamOfferDTO, ...] = ()
    # Полный JSON ответа для снимка, включая не разобранные редактором поля.
    raw_payload: dict[str, JsonValue]


class KeitaroStreamOfferInputDTO(FrozenBaseDTO):
    """Элемент полного списка привязок, отправляемого при публикации."""

    offer_id: KeitaroID
    share: OfferShare
    state: Literal["active", "disabled"] = "active"
