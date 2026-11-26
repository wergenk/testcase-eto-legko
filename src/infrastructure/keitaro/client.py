from collections.abc import Sequence
from copy import deepcopy
from functools import lru_cache
from types import TracebackType
from typing import Self

import httpx
from pydantic import JsonValue, TypeAdapter, ValidationError

from src.config import KeitaroSettings
from src.core.dto.keitaro import (
    KeitaroCampaignDTO,
    KeitaroCampaignInputDTO,
    KeitaroCampaignSummaryDTO,
    KeitaroCatalogItemDTO,
    KeitaroOfferDTO,
    KeitaroStreamDTO,
    KeitaroStreamInputDTO,
    KeitaroStreamOfferInputDTO,
)
from src.core.exceptions import (
    KeitaroAuthorizationError,
    KeitaroError,
    KeitaroNotFoundError,
    KeitaroTimeoutError,
)
from src.core.interfaces import KeitaroGateway

from .schemas import (
    CampaignIdentityResponse,
    CampaignResponse,
    CampaignSummaryResponse,
    CatalogItemResponse,
    OfferResponse,
    StreamResponse,
)


class HttpKeitaroGateway(KeitaroGateway):
    """Один переиспользуемый HTTP-клиент; закрывается через aclose/async with."""

    def __init__(
        self,
        settings: KeitaroSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=str(settings.base_url).rstrip("/") + "/",
            headers={
                "Api-Key": settings.api_key.get_secret_value(),
                "Accept": "application/json",
            },
            timeout=settings.timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        await self.aclose()
        return False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_campaigns(self) -> list[KeitaroCampaignSummaryDTO]:
        campaigns = []
        seen: set[int] = set()
        offset = 0
        while True:
            payload = await self._request(
                "GET", "campaigns", params={"offset": offset, "limit": 100}
            )
            page = self._validate(list[CampaignSummaryResponse], payload)
            for row in page:
                if row.id in seen:
                    raise KeitaroError("Keitaro повторил страницу кампаний")
                seen.add(row.id)
                campaigns.append(row.model_dump())
            if len(page) < 100:
                return self._validate(list[KeitaroCampaignSummaryDTO], campaigns)
            offset += len(page)

    async def find_campaign_by_alias(self, alias: str) -> KeitaroCampaignDTO | None:
        offset = 0
        seen: set[int] = set()
        found = None
        while True:
            payload = await self._request(
                "GET", "campaigns", params={"offset": offset, "limit": 100}
            )
            page = self._validate(list[CampaignIdentityResponse], payload)
            for row in page:
                if row.id in seen:
                    raise KeitaroError("Keitaro повторил страницу кампаний")
                seen.add(row.id)
                if row.alias == alias:
                    if found is not None:
                        raise KeitaroError("В Keitaro повторяется alias кампании")
                    found = await self.get_campaign(row.id)
            if len(page) < 100:
                return found
            offset += len(page)

    async def get_campaign(self, campaign_id: int) -> KeitaroCampaignDTO:
        self._validate_id(campaign_id)
        response = self._validate(
            CampaignResponse, await self._request("GET", f"campaigns/{campaign_id}")
        )
        return self._validate(KeitaroCampaignDTO, response.model_dump())

    async def create_campaign(
        self, data: KeitaroCampaignInputDTO
    ) -> KeitaroCampaignDTO:
        response = self._validate(
            CampaignResponse,
            await self._request("POST", "campaigns", json=data.model_dump(mode="json")),
        )
        return self._validate(KeitaroCampaignDTO, response.model_dump())

    async def set_campaign_state(
        self, campaign_id: int, *, active: bool
    ) -> KeitaroCampaignDTO:
        self._validate_id(campaign_id)
        response = self._validate(
            CampaignResponse,
            await self._request(
                "PUT",
                f"campaigns/{campaign_id}",
                json={"state": "active" if active else "disabled"},
            ),
        )
        return self._validate(KeitaroCampaignDTO, response.model_dump())

    async def create_stream(self, data: KeitaroStreamInputDTO) -> KeitaroStreamDTO:
        payload = await self._request(
            "POST", "streams", json=data.model_dump(mode="json", by_alias=True)
        )
        return self._to_stream(self._validate(StreamResponse, payload), payload)

    async def _list_catalog(
        self, path: str, **params: str
    ) -> list[KeitaroCatalogItemDTO]:
        rows = self._validate(
            list[CatalogItemResponse], await self._request("GET", path, params=params)
        )
        return self._validate(
            list[KeitaroCatalogItemDTO], [row.model_dump() for row in rows]
        )

    async def list_domains(self) -> list[KeitaroCatalogItemDTO]:
        return await self._list_catalog("domains")

    async def list_campaign_groups(self) -> list[KeitaroCatalogItemDTO]:
        return await self._list_catalog("groups", type="campaigns")

    async def list_traffic_sources(self) -> list[KeitaroCatalogItemDTO]:
        return await self._list_catalog("traffic_sources")

    async def get_campaign_streams(self, campaign_id: int) -> list[KeitaroStreamDTO]:
        self._validate_id(campaign_id)
        payload = await self._request("GET", f"campaigns/{campaign_id}/streams")
        streams = self._validate(list[StreamResponse], payload)
        return [
            self._to_stream(stream, raw)
            for stream, raw in zip(streams, payload, strict=True)
        ]

    async def get_stream(self, stream_id: int) -> KeitaroStreamDTO:
        self._validate_id(stream_id)
        payload = await self._request("GET", f"streams/{stream_id}")
        return self._to_stream(self._validate(StreamResponse, payload), payload)

    async def list_offers(self) -> list[KeitaroOfferDTO]:
        payload = await self._request("GET", "offers")
        offers = self._validate(list[OfferResponse], payload)
        return self._validate(
            list[KeitaroOfferDTO], [offer.model_dump() for offer in offers]
        )

    async def get_offer(self, offer_id: int) -> KeitaroOfferDTO:
        self._validate_id(offer_id)
        payload = await self._request("GET", f"offers/{offer_id}")
        offer = self._validate(OfferResponse, payload)
        return self._validate(KeitaroOfferDTO, offer.model_dump())

    async def replace_stream_offers(
        self,
        stream_id: int,
        offers: Sequence[KeitaroStreamOfferInputDTO],
    ) -> KeitaroStreamDTO:
        self._validate_id(stream_id)
        payload = await self._request(
            "PUT",
            f"streams/{stream_id}",
            json={"offers": [offer.model_dump(mode="json") for offer in offers]},
        )
        return self._to_stream(self._validate(StreamResponse, payload), payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, JsonValue] | None = None,
        params: dict[str, str | int] | None = None,
    ) -> JsonValue:
        try:
            response = await self._client.request(
                method, path, json=json, params=params
            )
        except httpx.TimeoutException:
            raise KeitaroTimeoutError("Истекло время ожидания ответа Keitaro") from None
        except httpx.RequestError:
            raise KeitaroError("Не удалось выполнить запрос к Keitaro") from None

        if response.status_code == 404:
            raise KeitaroNotFoundError("Запрошенный объект Keitaro не найден")
        if response.status_code in (401, 403):
            raise KeitaroAuthorizationError("Keitaro отклонил авторизацию или доступ")
        if not response.is_success:
            raise KeitaroError(f"Keitaro вернул HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError:
            raise KeitaroError("Keitaro вернул некорректный JSON") from None

    @staticmethod
    @lru_cache(maxsize=64)
    def _get_adapter[T](_type: type[T]) -> TypeAdapter[T]:
        return TypeAdapter(_type)

    @classmethod
    def _validate[T](cls, _type: type[T], values: object) -> T:
        try:
            return cls._get_adapter(_type).validate_python(values)
        except ValidationError:
            # Ошибка не содержит тело ответа, заголовки или API-ключ.
            raise KeitaroError(
                "Ответ Keitaro не соответствует ожидаемой схеме"
            ) from None

    @classmethod
    def _to_stream(cls, stream: StreamResponse, raw: JsonValue) -> KeitaroStreamDTO:
        return cls._validate(
            KeitaroStreamDTO,
            {**stream.model_dump(), "raw_payload": deepcopy(raw)},
        )

    @staticmethod
    def _validate_id(value: int) -> None:
        if type(value) is not int or value <= 0:
            raise ValueError(
                "Идентификатор Keitaro должен быть положительным целым числом"
            )
