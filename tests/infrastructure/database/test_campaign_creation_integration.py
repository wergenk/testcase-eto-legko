import asyncio
from copy import deepcopy
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.core.dto.campaign_creation import (
    CampaignCreationAttempt,
    CampaignCreationDefaults,
    CreateCampaignDTO,
)
from src.core.dto.keitaro import (
    KeitaroCampaignDTO,
    KeitaroCampaignInputDTO,
    KeitaroCatalogItemDTO,
    KeitaroOfferDTO,
    KeitaroStreamDTO,
    KeitaroStreamInputDTO,
)
from src.core.exceptions import (
    CampaignCreationConflictError,
    CampaignCreationError,
    KeitaroTimeoutError,
)
from src.core.interfaces import KeitaroGateway
from src.core.services import CampaignCreationService
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.repositories.campaign_creation import (
    CampaignCreationSQLAlchemyRepository,
)
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy

pytestmark = pytest.mark.asyncio


@pytest.fixture
def remote() -> Mock:
    gateway = create_autospec(KeitaroGateway, instance=True)
    gateway.campaign = None
    gateway.streams = []
    gateway.fail_after = None

    def fail(point: str) -> None:
        if gateway.fail_after == point:
            gateway.fail_after = None
            raise KeitaroTimeoutError("Ответ потерян")

    async def create_campaign(data: KeitaroCampaignInputDTO) -> KeitaroCampaignDTO:
        gateway.campaign = KeitaroCampaignDTO(id=100, **data.model_dump())
        fail("campaign")
        return gateway.campaign

    async def create_stream(data: KeitaroStreamInputDTO) -> KeitaroStreamDTO:
        payload = data.model_dump(mode="json", by_alias=True)
        stream = KeitaroStreamDTO(
            id=200 + len(gateway.streams),
            campaign_id=100,
            name=data.name,
            offers=data.offers,
            raw_payload={"id": 200 + len(gateway.streams), **payload},
        )
        gateway.streams.append(stream)
        fail(data.name)
        return stream

    async def activate(campaign_id: int, *, active: bool) -> KeitaroCampaignDTO:
        assert campaign_id == 100
        gateway.campaign = gateway.campaign.model_copy(
            update={"state": "active" if active else "disabled"}
        )
        fail("active")
        return gateway.campaign

    gateway.create_campaign.side_effect = create_campaign
    gateway.create_stream.side_effect = create_stream
    gateway.set_campaign_state.side_effect = activate
    gateway.find_campaign_by_alias.side_effect = lambda alias: gateway.campaign
    gateway.get_campaign.side_effect = lambda campaign_id: gateway.campaign
    gateway.get_campaign_streams.side_effect = lambda campaign_id: deepcopy(
        gateway.streams
    )
    gateway.list_domains.return_value = [KeitaroCatalogItemDTO(id=1)]
    gateway.list_campaign_groups.return_value = [KeitaroCatalogItemDTO(id=2)]
    gateway.list_traffic_sources.return_value = [KeitaroCatalogItemDTO(id=3)]
    offer = KeitaroOfferDTO(id=18003, name="Test", state="active")
    gateway.get_offer.return_value = offer
    gateway.list_offers.return_value = [offer]
    return gateway


@pytest.fixture
def command() -> CreateCampaignDTO:
    return CreateCampaignDTO(
        request_id=uuid4(), name="[TEST] Creator", country_code=" au ", offer_id=18003
    )


@pytest.fixture
def service(
    manager: AsyncDatabaseSessionManager, remote: Mock
) -> CampaignCreationService:
    return CampaignCreationService(
        lambda: StreamUnitOfWorkSQLAlchemy(manager),
        remote,
        CampaignCreationDefaults(domain_id=1, group_id=2, traffic_source_id=3),
    )


async def test_create_import_and_repeat(
    service: CampaignCreationService,
    remote: Mock,
    command: CreateCampaignDTO,
    manager: AsyncDatabaseSessionManager,
) -> None:
    result = await service.create_campaign(command)
    assert result == await service.create_campaign(command)
    assert (await service.get_attempt(command.request_id)).stage == "completed"
    assert remote.campaign.state == "active"
    assert len(remote.streams) == 2
    assert remote.streams[0].raw_payload["filters"][0]["payload"] == ["AU"]
    assert remote.streams[1].offers[0].share == 100
    remote.create_campaign.assert_awaited_once()
    assert remote.create_stream.await_count == 2
    async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
        streams = await uow.streams.list_by_campaign(result.campaign_id)
        assert len(streams) == 2
        for stream in streams:
            draft = await uow.drafts.get_by_stream(stream.id)
            assert not draft.is_dirty


@pytest.mark.parametrize("point", ["campaign", "GEO", "Offers", "active"])
async def test_lost_remote_response_is_reconciled(
    service: CampaignCreationService,
    remote: Mock,
    command: CreateCampaignDTO,
    point: str,
) -> None:
    remote.fail_after = point
    with pytest.raises(KeitaroTimeoutError):
        await service.create_campaign(command)
    result = await service.create_campaign(command)
    assert result.campaign_id == 100
    remote.create_campaign.assert_awaited_once()
    assert remote.create_stream.await_count == 2
    remote.set_campaign_state.assert_awaited_once()


@pytest.mark.parametrize("stage", ["campaign", "geo", "offers", "active", "completed"])
async def test_failed_local_checkpoint_can_resume(
    service: CampaignCreationService,
    remote: Mock,
    command: CreateCampaignDTO,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    original = CampaignCreationSQLAlchemyRepository.update
    failed = False

    async def update(
        self: CampaignCreationSQLAlchemyRepository, attempt: CampaignCreationAttempt
    ) -> None:
        nonlocal failed
        if attempt.stage == stage and not failed:
            failed = True
            raise RuntimeError("Database write failed")
        await original(self, attempt)

    monkeypatch.setattr(CampaignCreationSQLAlchemyRepository, "update", update)
    with pytest.raises(RuntimeError, match="Database write"):
        await service.create_campaign(command)
    await service.create_campaign(command)
    remote.create_campaign.assert_awaited_once()
    assert remote.create_stream.await_count == 2
    remote.set_campaign_state.assert_awaited_once()


async def test_parallel_requests_create_one_campaign(
    service: CampaignCreationService, remote: Mock, command: CreateCampaignDTO
) -> None:
    results = await asyncio.gather(
        *(service.create_campaign(command) for _ in range(3))
    )
    assert results[0] == results[1] == results[2]
    remote.create_campaign.assert_awaited_once()
    assert remote.create_stream.await_count == 2


async def test_reusing_request_id_with_changed_input_is_conflict(
    service: CampaignCreationService, remote: Mock, command: CreateCampaignDTO
) -> None:
    await service.create_campaign(command)
    with pytest.raises(CampaignCreationConflictError):
        await service.create_campaign(command.model_copy(update={"name": "Other"}))
    remote.create_campaign.assert_awaited_once()


@pytest.mark.parametrize("reference", ["offer", "domain", "group", "source"])
async def test_invalid_references_do_not_create_remote_campaign(
    service: CampaignCreationService,
    remote: Mock,
    command: CreateCampaignDTO,
    reference: str,
) -> None:
    if reference == "offer":
        remote.get_offer.return_value = KeitaroOfferDTO(
            id=18003, name="Test", state="disabled"
        )
    else:
        getattr(
            remote,
            {
                "domain": "list_domains",
                "group": "list_campaign_groups",
                "source": "list_traffic_sources",
            }[reference],
        ).return_value = []
    with pytest.raises(CampaignCreationError):
        await service.create_campaign(command)
    remote.create_campaign.assert_not_awaited()


async def test_changed_remote_stream_is_not_overwritten(
    service: CampaignCreationService, remote: Mock, command: CreateCampaignDTO
) -> None:
    remote.fail_after = "GEO"
    with pytest.raises(KeitaroTimeoutError):
        await service.create_campaign(command)
    payload = deepcopy(remote.streams[0].raw_payload)
    payload["filters"][0]["payload"] = ["DE"]
    remote.streams[0] = remote.streams[0].model_copy(update={"raw_payload": payload})
    with pytest.raises(CampaignCreationConflictError):
        await service.create_campaign(command)
    assert remote.campaign.state == "disabled"
    remote.set_campaign_state.assert_not_awaited()


async def test_retry_uses_saved_defaults(
    service: CampaignCreationService, remote: Mock, command: CreateCampaignDTO
) -> None:
    remote.fail_after = "campaign"
    with pytest.raises(KeitaroTimeoutError):
        await service.create_campaign(command)
    service._defaults = CampaignCreationDefaults(
        domain_id=9, group_id=9, traffic_source_id=9
    )
    await service.create_campaign(command)
    assert remote.campaign.domain_id == 1


async def test_creation_works_with_single_connection_pool(
    manager: AsyncDatabaseSessionManager, remote: Mock, command: CreateCampaignDTO
) -> None:
    async with manager.engine.connect() as connection:
        schema = await connection.scalar(select(func.current_schema()))
    limited = AsyncDatabaseSessionManager(
        manager.engine.url.render_as_string(hide_password=False),
        pool_size=1,
        max_overflow=0,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        service = CampaignCreationService(
            lambda: StreamUnitOfWorkSQLAlchemy(limited),
            remote,
            CampaignCreationDefaults(domain_id=1, group_id=2, traffic_source_id=3),
        )
        result = await asyncio.wait_for(service.create_campaign(command), timeout=5)
        assert result.campaign_id == 100
    finally:
        await limited.shutdown()
