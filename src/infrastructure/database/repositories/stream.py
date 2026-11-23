from sqlalchemy import select

from src.core.dto import CreateStreamDTO, Stream
from src.core.interfaces.repositories import StreamRepository
from src.infrastructure.database.models import StreamORM

from .base import BaseRepository


class StreamSQLAlchemyRepository(BaseRepository, StreamRepository):
    async def _get_orm(self, stream_id: int) -> StreamORM | None:
        stmt = (
            select(StreamORM)
            .where(StreamORM.id == stream_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def create(self, data: CreateStreamDTO) -> Stream:
        stream_orm = StreamORM(**data.model_dump())
        self.session.add(stream_orm)
        await self.session.flush()
        return self._validate(Stream, stream_orm)

    async def get(self, stream_id: int) -> Stream | None:
        return self._validate(Stream, await self._get_orm(stream_id))

    async def get_by_keitaro_id(self, keitaro_stream_id: int) -> Stream | None:
        stmt = (
            select(StreamORM)
            .where(StreamORM.keitaro_stream_id == keitaro_stream_id)
            .execution_options(populate_existing=True)
        )
        stream_orm = (await self.session.execute(stmt)).scalars().one_or_none()
        return self._validate(Stream, stream_orm)

    async def list_by_campaign(self, keitaro_campaign_id: int) -> list[Stream]:
        stmt = (
            select(StreamORM)
            .where(StreamORM.keitaro_campaign_id == keitaro_campaign_id)
            .order_by(StreamORM.id)
            .execution_options(populate_existing=True)
        )
        streams = (await self.session.execute(stmt)).scalars().all()
        return self._validate(list[Stream], streams)

    async def update(self, stream: Stream) -> None:
        stream_orm = await self._get_orm(stream.id)
        if (
            stream_orm is None
            or stream_orm.keitaro_stream_id != stream.keitaro_stream_id
        ):
            raise ValueError("Поток отсутствует или его Keitaro ID изменён")
        stream_orm.name = stream.name
        stream_orm.keitaro_campaign_id = stream.keitaro_campaign_id
        await self.session.flush()
