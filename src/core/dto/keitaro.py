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


class KeitaroCatalogItemDTO(FrozenBaseDTO):
    id: KeitaroID


class KeitaroCampaignSummaryDTO(FrozenBaseDTO):
    id: KeitaroID
    name: str
    alias: str
    state: str


class KeitaroCampaignDTO(FrozenBaseDTO):
    id: KeitaroID
    name: str
    alias: str
    domain_id: KeitaroID
    group_id: KeitaroID
    traffic_source_id: KeitaroID
    state: str
    type: str


class KeitaroCampaignInputDTO(FrozenBaseDTO):
    name: str
    alias: str
    domain_id: KeitaroID
    group_id: KeitaroID
    traffic_source_id: KeitaroID
    state: Literal["active", "disabled"] = "disabled"
    type: Literal["position"] = "position"


class KeitaroStreamInputDTO(FrozenBaseDTO):
    campaign_id: KeitaroID
    name: str
    type: Literal["regular", "default"]
    stream_schema: Literal["redirect", "landings"] = Field(alias="schema")
    position: int = Field(ge=1)
    state: Literal["active"] = "active"
    action_type: Literal["http"] = "http"
    action_payload: str = ""
    filters: tuple[dict[str, JsonValue], ...] = ()
    filter_or: bool = False
    collect_clicks: bool = True
    offer_selection: Literal["before_click"] = "before_click"
    offers: tuple[KeitaroStreamOfferInputDTO, ...] = ()
    landings: tuple[dict[str, JsonValue], ...] = ()
