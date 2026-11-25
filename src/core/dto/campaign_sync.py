from pydantic import Field

from .base import BaseDTO
from .stream import Stream
from .stream_draft import StreamDraft


class FetchedStreamDTO(BaseDTO):
    stream: Stream
    draft: StreamDraft


class CampaignFetchResultDTO(BaseDTO):
    keitaro_campaign_id: int = Field(gt=0)
    streams: tuple[FetchedStreamDTO, ...]
