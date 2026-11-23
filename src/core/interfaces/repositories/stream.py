from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.core.dto import CreateStreamDTO, Stream


class StreamRepository(ABC):
    """Локальные потоки. Методы не коммитят транзакцию самостоятельно."""

    @abstractmethod
    async def create(self, data: CreateStreamDTO) -> Stream:
        """Создать поток с уникальным keitaro_stream_id."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, stream_id: int) -> Stream | None:
        """Найти поток по локальному идентификатору."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_keitaro_id(self, keitaro_stream_id: int) -> Stream | None:
        """Найти поток по идентификатору Keitaro."""
        raise NotImplementedError

    @abstractmethod
    async def list_by_campaign(self, keitaro_campaign_id: int) -> Sequence[Stream]:
        """Вернуть потоки кампании в порядке локального id."""
        raise NotImplementedError

    @abstractmethod
    async def update(self, stream: Stream) -> None:
        """Обновить данные существующего потока, сохранив его идентичность."""
        raise NotImplementedError
