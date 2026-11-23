from copy import deepcopy

from sqlalchemy import select

from src.core.dto import CreateStreamSnapshotDTO, StreamSnapshot
from src.core.interfaces.repositories import StreamSnapshotRepository
from src.infrastructure.database.models import StreamSnapshotORM

from .base import BaseRepository


class StreamSnapshotSQLAlchemyRepository(BaseRepository, StreamSnapshotRepository):
    async def create(self, data: CreateStreamSnapshotDTO) -> StreamSnapshot:
        snapshot_orm = StreamSnapshotORM(
            stream_id=data.stream_id, payload=deepcopy(data.payload)
        )
        self.session.add(snapshot_orm)
        await self.session.flush()
        return self._validate(StreamSnapshot, snapshot_orm)

    async def get(self, snapshot_id: int) -> StreamSnapshot | None:
        stmt = (
            select(StreamSnapshotORM)
            .where(StreamSnapshotORM.id == snapshot_id)
            .execution_options(populate_existing=True)
        )
        snapshot_orm = (await self.session.execute(stmt)).scalars().one_or_none()
        return self._validate(StreamSnapshot, snapshot_orm)

    async def get_latest(self, stream_id: int) -> StreamSnapshot | None:
        stmt = (
            select(StreamSnapshotORM)
            .where(StreamSnapshotORM.stream_id == stream_id)
            .order_by(StreamSnapshotORM.created_at.desc(), StreamSnapshotORM.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        snapshot_orm = (await self.session.execute(stmt)).scalars().one_or_none()
        return self._validate(StreamSnapshot, snapshot_orm)
