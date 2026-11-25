from uuid import UUID

from sqlalchemy import func, select

from src.core.dto.campaign_creation import (
    CampaignCreationAttempt,
    CampaignCreationDefaults,
    CreateCampaignDTO,
)
from src.core.interfaces.repositories.campaign_creation import (
    CampaignCreationRepository,
)
from src.infrastructure.database.models.campaign_creation import (
    CampaignCreationAttemptORM,
)

from .base import BaseRepository


class CampaignCreationSQLAlchemyRepository(BaseRepository, CampaignCreationRepository):
    async def lock(self, request_id: UUID) -> None:
        resource = f"adrobot:creation:{request_id}"
        stmt = select(func.pg_advisory_xact_lock(func.hashtextextended(resource, 0)))
        await self.session.execute(stmt)

    async def _get_orm(self, request_id: UUID) -> CampaignCreationAttemptORM | None:
        stmt = (
            select(CampaignCreationAttemptORM)
            .where(CampaignCreationAttemptORM.request_id == request_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalars().one_or_none()

    async def get(self, request_id: UUID) -> CampaignCreationAttempt | None:
        return self._validate(CampaignCreationAttempt, await self._get_orm(request_id))

    async def create(
        self, command: CreateCampaignDTO, defaults: CampaignCreationDefaults
    ) -> CampaignCreationAttempt:
        model = CampaignCreationAttemptORM(
            request_id=command.request_id,
            command=command.model_dump(mode="json"),
            defaults=defaults.model_dump(mode="json"),
        )
        self.session.add(model)
        await self.session.flush()
        return self._validate(CampaignCreationAttempt, model)

    async def update(self, attempt: CampaignCreationAttempt) -> None:
        model = await self._get_orm(attempt.request_id)
        if model is None:
            raise ValueError("Попытка создания кампании не найдена")
        model.stage = attempt.stage
        model.campaign_id = attempt.campaign_id
        model.geo_stream_id = attempt.geo_stream_id
        model.offers_stream_id = attempt.offers_stream_id
        await self.session.flush()
