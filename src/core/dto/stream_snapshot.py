from datetime import datetime

from pydantic import Field, JsonValue

from .base import FrozenBaseDTO


class CreateStreamSnapshotDTO(FrozenBaseDTO):
    stream_id: int = Field(gt=0)
    payload: dict[str, JsonValue]


class StreamSnapshot(CreateStreamSnapshotDTO):
    id: int = Field(gt=0)
    created_at: datetime
