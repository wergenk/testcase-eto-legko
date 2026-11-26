from collections.abc import AsyncIterator, Callable
from functools import partial
from typing import Annotated

from fastapi import Depends, Request

from src.core.interfaces import StreamUnitOfWork
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy

type StreamUowFactory = Callable[[], StreamUnitOfWork]


def get_uow_factory(request: Request) -> StreamUowFactory:
    return partial(StreamUnitOfWorkSQLAlchemy, request.app.state.session_manager)


StreamUowFactoryDepend = Annotated[StreamUowFactory, Depends(get_uow_factory)]


async def get_stream_uow(
    factory: StreamUowFactoryDepend,
) -> AsyncIterator[StreamUnitOfWork]:
    """Открыть UOW для чтения и закрыть транзакцию без commit."""
    async with factory() as uow:
        yield uow


StreamUowDepend = Annotated[StreamUnitOfWork, Depends(get_stream_uow, scope="function")]
