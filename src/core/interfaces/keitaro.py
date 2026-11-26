from abc import ABC, abstractmethod
from collections.abc import Sequence

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


class KeitaroGateway(ABC):
    """Внешний контракт редактора; все идентификаторы относятся к Keitaro.

    Адаптер преобразует ответы API в DTO, сохраняя полный JSON потока
    в raw_payload. Ошибки интеграции преобразуются в KeitaroError,
    отсутствие запрошенного объекта — в KeitaroNotFoundError.
    HTTP-типы и настройки клиента остаются в infrastructure.
    """

    @abstractmethod
    async def list_campaigns(self) -> Sequence[KeitaroCampaignSummaryDTO]:
        """Получить все страницы кампаний для выбора в редакторе."""
        raise NotImplementedError

    @abstractmethod
    async def find_campaign_by_alias(self, alias: str) -> KeitaroCampaignDTO | None:
        raise NotImplementedError

    @abstractmethod
    async def get_campaign(self, campaign_id: int) -> KeitaroCampaignDTO:
        raise NotImplementedError

    @abstractmethod
    async def create_campaign(
        self, data: KeitaroCampaignInputDTO
    ) -> KeitaroCampaignDTO:
        raise NotImplementedError

    @abstractmethod
    async def set_campaign_state(
        self, campaign_id: int, *, active: bool
    ) -> KeitaroCampaignDTO:
        raise NotImplementedError

    @abstractmethod
    async def create_stream(self, data: KeitaroStreamInputDTO) -> KeitaroStreamDTO:
        raise NotImplementedError

    @abstractmethod
    async def list_domains(self) -> Sequence[KeitaroCatalogItemDTO]:
        raise NotImplementedError

    @abstractmethod
    async def list_campaign_groups(self) -> Sequence[KeitaroCatalogItemDTO]:
        raise NotImplementedError

    @abstractmethod
    async def list_traffic_sources(self) -> Sequence[KeitaroCatalogItemDTO]:
        raise NotImplementedError

    @abstractmethod
    async def get_campaign_streams(
        self,
        campaign_id: int,
    ) -> Sequence[KeitaroStreamDTO]:
        """Загрузить все потоки кампании, включая потоки без офферов.

        GET /campaigns/{id}/streams. Пустой список означает, что в кампании
        нет потоков; отсутствие самой кампании не маскируется пустым списком.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_stream(self, stream_id: int) -> KeitaroStreamDTO:
        """GET /streams/{id}: получить текущее состояние и привязки офферов."""
        raise NotImplementedError

    @abstractmethod
    async def list_offers(self) -> Sequence[KeitaroOfferDTO]:
        """GET /offers: получить каталог для локального поиска по ID/названию."""
        raise NotImplementedError

    @abstractmethod
    async def get_offer(self, offer_id: int) -> KeitaroOfferDTO:
        """GET /offers/{id}: получить оффер, проверив его существование."""
        raise NotImplementedError

    @abstractmethod
    async def replace_stream_offers(
        self,
        stream_id: int,
        offers: Sequence[KeitaroStreamOfferInputDTO],
    ) -> KeitaroStreamDTO:
        """PUT /streams/{id}: заменить полный список привязок офферов.

        Отправить только поле offers, сохранив остальные настройки потока.
        Пустой список очищает привязки. Локальный архив и is_pinned
        не отправляются. Проверка состава и расчёт долей выполняются
        сервисом до вызова; gateway не пересчитывает доли самостоятельно.
        Вернуть состояние из ответа Keitaro, а не копию отправленных данных.
        """
        raise NotImplementedError
