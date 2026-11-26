from src.core.dto import CreateCampaignDTO, Stream
from src.core.dto.base import BaseDTO

from .draft import StreamDraftResponse


class CreateCampaignRequest(CreateCampaignDTO):
    """request_id сохраняется клиентом для повторов одной операции."""


class CampaignStreamResponse(BaseDTO):
    stream: Stream
    draft: StreamDraftResponse


class CampaignStreamsResponse(BaseDTO):
    keitaro_campaign_id: int
    streams: tuple[CampaignStreamResponse, ...]
