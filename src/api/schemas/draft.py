from datetime import datetime

from pydantic import Field

from src.core.dto import DraftOfferDTO
from src.core.dto.base import BaseDTO
from src.core.dto.keitaro import KeitaroID, OfferShare


class RevisionRequest(BaseDTO):
    expected_revision: int = Field(strict=True, gt=0)


class AddOfferRequest(RevisionRequest):
    offer_id: KeitaroID


class PinShareRequest(RevisionRequest):
    share: OfferShare


class StreamDraftResponse(BaseDTO):
    id: int
    stream_id: int
    revision: int
    offers: tuple[DraftOfferDTO, ...]
    is_dirty: bool
    created_at: datetime
    updated_at: datetime
