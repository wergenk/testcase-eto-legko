from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class AsyncDatabaseSessionManager:
    def __init__(self, db_url: str, **engine_kwargs: object) -> None:
        options: dict[str, object] = {"pool_pre_ping": True}
        options.update(engine_kwargs)
        self.engine: AsyncEngine = create_async_engine(db_url, **options)
        self.async_session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
            close_resets_only=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Новая сессия; закрытие откатывает незавершённую транзакцию."""
        async with self.async_session_factory() as session:
            yield session

    async def shutdown(self) -> None:
        await self.engine.dispose()
