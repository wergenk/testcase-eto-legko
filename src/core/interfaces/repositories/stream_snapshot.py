from abc import ABC, abstractmethod

from src.core.dto import CreateStreamSnapshotDTO, StreamSnapshot


class StreamSnapshotRepository(ABC):
    """Снимки создаются один раз; изменение сохранённого снимка запрещено.

    Методы не коммитят транзакцию самостоятельно.
    """

    @abstractmethod
    async def create(self, data: CreateStreamSnapshotDTO) -> StreamSnapshot:
        """Сохранить независимую копию состояния, полученного из Keitaro."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, snapshot_id: int) -> StreamSnapshot | None:
        """Найти снимок по локальному идентификатору."""
        raise NotImplementedError

    @abstractmethod
    async def get_latest(self, stream_id: int) -> StreamSnapshot | None:
        """Вернуть последний снимок по created_at, затем id при равенстве дат."""
        raise NotImplementedError
