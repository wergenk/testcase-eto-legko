from abc import ABC, abstractmethod
from uuid import UUID

from src.core.dto.campaign_creation import (
    CampaignCreationAttempt,
    CampaignCreationDefaults,
    CreateCampaignDTO,
)


class CampaignCreationRepository(ABC):
    @abstractmethod
    async def lock(self, request_id: UUID) -> None:
        """Заблокировать ключ запроса до commit/rollback, даже без записи попытки."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, request_id: UUID) -> CampaignCreationAttempt | None:
        raise NotImplementedError

    @abstractmethod
    async def create(
        self, command: CreateCampaignDTO, defaults: CampaignCreationDefaults
    ) -> CampaignCreationAttempt:
        raise NotImplementedError

    @abstractmethod
    async def update(self, attempt: CampaignCreationAttempt) -> None:
        raise NotImplementedError
