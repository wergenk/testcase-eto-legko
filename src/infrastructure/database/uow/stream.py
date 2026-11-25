from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.interfaces.repositories import (
    StreamDraftRepository,
    StreamRepository,
    StreamSnapshotRepository,
)
from src.core.interfaces.repositories.campaign_creation import (
    CampaignCreationRepository,
)
from src.core.interfaces.uow import StreamUnitOfWork
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.repositories import (
    StreamDraftSQLAlchemyRepository,
    StreamSnapshotSQLAlchemyRepository,
    StreamSQLAlchemyRepository,
)
from src.infrastructure.database.repositories.campaign_creation import (
    CampaignCreationSQLAlchemyRepository,
)


class StreamUnitOfWorkSQLAlchemy(StreamUnitOfWork):
    def __init__(self, session_manager: AsyncDatabaseSessionManager) -> None:
        self._session_manager = session_manager
        self._session: AsyncSession | None = None
        self._streams: StreamRepository | None = None
        self._snapshots: StreamSnapshotRepository | None = None
        self._drafts: StreamDraftRepository | None = None
        self._creations: CampaignCreationRepository | None = None

    @property
    def creations(self) -> CampaignCreationRepository:
        self._require_session()
        if self._creations is None:
            raise RuntimeError("Репозиторий создания кампаний не инициализирован")
        return self._creations

    @property
    def streams(self) -> StreamRepository:
        self._require_session()
        if self._streams is None:
            raise RuntimeError("Репозиторий потоков не инициализирован")
        return self._streams

    @property
    def snapshots(self) -> StreamSnapshotRepository:
        self._require_session()
        if self._snapshots is None:
            raise RuntimeError("Репозиторий снимков не инициализирован")
        return self._snapshots

    @property
    def drafts(self) -> StreamDraftRepository:
        self._require_session()
        if self._drafts is None:
            raise RuntimeError("Репозиторий черновиков не инициализирован")
        return self._drafts

    async def __aenter__(self) -> Self:
        if self._session is not None:
            raise RuntimeError("Этот UnitOfWork уже открыт")
        session = self._session_manager.async_session_factory()
        try:
            await session.begin()
            self._streams = StreamSQLAlchemyRepository(session)
            self._snapshots = StreamSnapshotSQLAlchemyRepository(session)
            self._drafts = StreamDraftSQLAlchemyRepository(session)
            self._creations = CampaignCreationSQLAlchemyRepository(session)
            self._session = session
        except BaseException:
            await session.close()
            raise
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        session = self._require_session()
        try:
            await session.rollback()
        finally:
            try:
                await session.close()
            finally:
                self._session = None
                self._streams = None
                self._snapshots = None
                self._drafts = None
                self._creations = None
        return False

    async def commit(self) -> None:
        await self._require_session().commit()

    async def rollback(self) -> None:
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork нужно открыть через async with")
        return self._session
