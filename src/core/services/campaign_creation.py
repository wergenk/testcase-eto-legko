from collections.abc import Callable, Sequence
from uuid import UUID

from src.core.dto.campaign_creation import (
    CampaignCreationAttempt,
    CampaignCreationDefaults,
    CampaignCreationResultDTO,
    CreateCampaignDTO,
)
from src.core.dto.keitaro import (
    KeitaroCampaignDTO,
    KeitaroCampaignInputDTO,
    KeitaroStreamDTO,
    KeitaroStreamInputDTO,
    KeitaroStreamOfferInputDTO,
)
from src.core.exceptions import CampaignCreationConflictError, CampaignCreationError
from src.core.interfaces import KeitaroGateway, StreamUnitOfWork

from .campaign_sync import CampaignSyncService


class CampaignCreationService:
    """Этапы фиксируются отдельно; повтор POST сначала сверяет объекты Keitaro."""

    def __init__(
        self,
        uow_factory: Callable[[], StreamUnitOfWork],
        keitaro: KeitaroGateway,
        defaults: CampaignCreationDefaults,
    ) -> None:
        self._uow_factory = uow_factory
        self._keitaro = keitaro
        self._defaults = defaults
        self._sync = CampaignSyncService(uow_factory, keitaro)

    async def create_campaign(
        self, command: CreateCampaignDTO
    ) -> CampaignCreationResultDTO:
        while True:
            async with self._uow_factory() as uow:
                await uow.creations.lock(command.request_id)
                attempt = await uow.creations.get(command.request_id)
                if attempt is None:
                    await uow.creations.create(command, self._defaults)
                    await uow.commit()
                    continue
                if attempt.command != command:
                    raise CampaignCreationConflictError(
                        "request_id уже использован с другими параметрами"
                    )
                if attempt.stage == "completed":
                    return self._result(attempt)
                updated = await self._advance(attempt, uow)
                await uow.creations.update(updated)
                await uow.commit()

    async def get_attempt(self, request_id: UUID) -> CampaignCreationAttempt | None:
        async with self._uow_factory() as uow:
            res = await uow.creations.get(request_id)
        return res

    async def _advance(
        self, attempt: CampaignCreationAttempt, uow: StreamUnitOfWork
    ) -> CampaignCreationAttempt:
        if attempt.stage == "pending":
            await self._validate_references(attempt)
            data = self._campaign_input(attempt)
            remote = await self._keitaro.find_campaign_by_alias(data.alias)
            if remote is None:
                remote = await self._keitaro.create_campaign(data)
            self._ensure_campaign(remote, data)
            return attempt.model_copy(
                update={"campaign_id": remote.id, "stage": "campaign"}
            )
        if attempt.stage in ("campaign", "geo"):
            campaign = await self._keitaro.get_campaign(attempt.campaign_id)
            self._ensure_campaign(campaign, self._campaign_input(attempt))
            if campaign.state != "disabled":
                raise CampaignCreationConflictError(
                    "Незавершённая кампания включена извне"
                )
            geo = attempt.stage == "campaign"
            data = self._stream_input(attempt, geo=geo)
            streams = await self._keitaro.get_campaign_streams(attempt.campaign_id)
            remote = self._find_stream(streams, data)
            if remote is None:
                remote = await self._keitaro.create_stream(data)
            self._ensure_stream(remote, data)
            return attempt.model_copy(
                update={
                    "geo_stream_id" if geo else "offers_stream_id": remote.id,
                    "stage": "geo" if geo else "offers",
                }
            )
        if attempt.stage == "offers":
            streams = await self._keitaro.get_campaign_streams(attempt.campaign_id)
            if len(streams) != 2:
                raise CampaignCreationConflictError(
                    "Ожидались ровно два потока кампании"
                )
            for geo, stream_id in (
                (True, attempt.geo_stream_id),
                (False, attempt.offers_stream_id),
            ):
                stream = self._find_stream(
                    streams, self._stream_input(attempt, geo=geo)
                )
                if stream is None or stream.id != stream_id:
                    raise CampaignCreationConflictError(
                        "Потоки кампании изменены извне"
                    )
            campaign = await self._keitaro.get_campaign(attempt.campaign_id)
            self._ensure_campaign(campaign, self._campaign_input(attempt))
            if campaign.state != "active":
                if campaign.state != "disabled":
                    raise CampaignCreationConflictError(
                        "Неожиданное состояние кампании"
                    )
                campaign = await self._keitaro.set_campaign_state(
                    campaign.id, active=True
                )
                self._ensure_campaign(campaign, self._campaign_input(attempt))
                if campaign.state != "active":
                    raise CampaignCreationError(
                        "Keitaro не подтвердил включение кампании"
                    )
            return attempt.model_copy(update={"stage": "active"})
        await self._sync.fetch_campaign(attempt.campaign_id, uow=uow)
        return attempt.model_copy(update={"stage": "completed"})

    async def _validate_references(self, attempt: CampaignCreationAttempt) -> None:
        offer = await self._keitaro.get_offer(attempt.command.offer_id)
        if offer.id != attempt.command.offer_id or offer.state != "active":
            raise CampaignCreationError("Выбранный оффер недоступен")
        defaults = attempt.defaults
        for selected, catalog in (
            (defaults.domain_id, await self._keitaro.list_domains()),
            (defaults.group_id, await self._keitaro.list_campaign_groups()),
            (defaults.traffic_source_id, await self._keitaro.list_traffic_sources()),
        ):
            if selected not in {row.id for row in catalog}:
                raise CampaignCreationError(
                    "Домен, группа или источник отсутствует в Keitaro"
                )

    @staticmethod
    def _campaign_input(attempt: CampaignCreationAttempt) -> KeitaroCampaignInputDTO:
        return KeitaroCampaignInputDTO(
            name=attempt.command.name,
            alias="adrobot-" + attempt.request_id.hex,
            **attempt.defaults.model_dump(),
        )

    @staticmethod
    def _ensure_campaign(
        remote: KeitaroCampaignDTO, expected: KeitaroCampaignInputDTO
    ) -> None:
        fields = ("name", "alias", "domain_id", "group_id", "traffic_source_id", "type")
        if any(getattr(remote, field) != getattr(expected, field) for field in fields):
            raise CampaignCreationConflictError(
                "Кампания с этим alias содержит другие настройки"
            )

    @staticmethod
    def _stream_input(
        attempt: CampaignCreationAttempt, *, geo: bool
    ) -> KeitaroStreamInputDTO:
        if geo:
            return KeitaroStreamInputDTO(
                campaign_id=attempt.campaign_id,
                name="GEO",
                type="regular",
                schema="redirect",
                position=1,
                action_payload="https://www.google.com/",
                filters=(
                    {
                        "name": "country",
                        "mode": "accept",
                        "payload": [attempt.command.country_code],
                    },
                ),
            )
        return KeitaroStreamInputDTO(
            campaign_id=attempt.campaign_id,
            name="Offers",
            type="default",
            schema="landings",
            position=2,
            offers=(
                KeitaroStreamOfferInputDTO(
                    offer_id=attempt.command.offer_id, share=100
                ),
            ),
        )

    @classmethod
    def _find_stream(
        cls, streams: Sequence[KeitaroStreamDTO], data: KeitaroStreamInputDTO
    ) -> KeitaroStreamDTO | None:
        matches = [stream for stream in streams if stream.name == data.name]
        if len(matches) > 1:
            raise CampaignCreationConflictError("В кампании повторяется имя потока")
        if not matches:
            return None
        cls._ensure_stream(matches[0], data)
        return matches[0]

    @staticmethod
    def _ensure_stream(remote: KeitaroStreamDTO, data: KeitaroStreamInputDTO) -> None:
        expected = data.model_dump(mode="json", by_alias=True)
        fields = (
            "type",
            "schema",
            "position",
            "state",
            "filter_or",
            "landings",
            "collect_clicks",
            "offer_selection",
        )
        if data.stream_schema == "redirect":
            fields += ("action_type", "action_payload")
        if remote.campaign_id != data.campaign_id or remote.name != data.name:
            raise CampaignCreationConflictError("Keitaro вернул другой поток")
        if any(remote.raw_payload.get(field) != expected[field] for field in fields):
            raise CampaignCreationConflictError(
                "Настройки потока отличаются от ожидаемых"
            )
        filters = remote.raw_payload.get("filters", [])
        if not isinstance(filters, list):
            raise CampaignCreationConflictError("Некорректный список фильтров")
        actual = [
            {key: row.get(key) for key in ("name", "mode", "payload")}
            for row in filters
            if isinstance(row, dict)
        ]
        if actual != expected["filters"] or len(actual) != len(filters):
            raise CampaignCreationConflictError(
                "GEO-фильтры потока отличаются от ожидаемых"
            )
        links = tuple((row.offer_id, row.share, row.state) for row in remote.offers)
        if links != tuple((row.offer_id, row.share, row.state) for row in data.offers):
            raise CampaignCreationConflictError(
                "Состав офферов потока отличается от ожидаемого"
            )

    @staticmethod
    def _result(attempt: CampaignCreationAttempt) -> CampaignCreationResultDTO:
        return CampaignCreationResultDTO(
            request_id=attempt.request_id,
            campaign_id=attempt.campaign_id,
            geo_stream_id=attempt.geo_stream_id,
            offers_stream_id=attempt.offers_stream_id,
        )
