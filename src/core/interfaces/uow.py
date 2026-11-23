from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from .repositories import (
    StreamDraftRepository,
    StreamRepository,
    StreamSnapshotRepository,
)


class UnitOfWork(ABC):
    """Транзакция с явным commit; выход откатывает незафиксированные изменения."""

    @abstractmethod
    async def __aenter__(self) -> Self:
        raise NotImplementedError

    @abstractmethod
    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def commit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def rollback(self) -> None:
        raise NotImplementedError


class StreamUnitOfWork(UnitOfWork):
    @property
    @abstractmethod
    def streams(self) -> StreamRepository:
        raise NotImplementedError

    @property
    @abstractmethod
    def snapshots(self) -> StreamSnapshotRepository:
        raise NotImplementedError

    @property
    @abstractmethod
    def drafts(self) -> StreamDraftRepository:
        raise NotImplementedError
