from datetime import datetime

from pydantic import Field

from .base import BaseDTO


class CreateStreamDTO(BaseDTO):
    keitaro_stream_id: int = Field(gt=0)
    keitaro_campaign_id: int = Field(gt=0)
    name: str


class Stream(CreateStreamDTO):
    id: int = Field(gt=0)
    created_at: datetime
