from datetime import datetime

from pydantic import Field

from .base import BaseDTO, FrozenBaseDTO


class DraftOfferDTO(FrozenBaseDTO):
    """Строка редактора; архивные офферы тоже входят в состав черновика."""

    keitaro_offer_id: int = Field(gt=0)
    name: str
    share: int = Field(strict=True, ge=0, le=100)
    is_pinned: bool
    is_active: bool
    position: int = Field(ge=0)


class CreateStreamDraftDTO(BaseDTO):
    stream_id: int = Field(gt=0)
    base_snapshot_id: int = Field(gt=0)
    offers: tuple[DraftOfferDTO, ...]
    # Локальное состояние для Cancel, включая архив и закрепления долей.
    base_editor_state: tuple[DraftOfferDTO, ...]


class StreamDraft(CreateStreamDraftDTO):
    id: int = Field(gt=0)
    revision: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime

    @property
    def is_dirty(self) -> bool:
        """Порядок объектов в DTO не важен; position входит в состояние строки."""
        current = {offer.keitaro_offer_id: offer for offer in self.offers}
        baseline = {offer.keitaro_offer_id: offer for offer in self.base_editor_state}
        return current != baseline
