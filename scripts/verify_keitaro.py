"""Явная живая проверка: uv run python -m scripts.verify_keitaro --help."""

import argparse
import asyncio
import os
from uuid import UUID, uuid4

from alembic.config import Config
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command as migrations
from src.config import get_settings
from src.core.dto.campaign_creation import CampaignCreationDefaults, CreateCampaignDTO
from src.core.services import (
    CampaignCreationService,
    CampaignSyncService,
    StreamDraftService,
)
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy
from src.infrastructure.keitaro import HttpKeitaroGateway


def migrate(connection: Connection) -> None:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    migrations.upgrade(config, "head")


async def verify(args: argparse.Namespace) -> None:
    url = os.environ["TEST_DATABASE_URL"]
    if not (make_url(url).database or "").startswith("adrobot_test"):
        raise ValueError("Проверка требует отдельную базу adrobot_test*")
    settings = get_settings()
    if settings.keitaro is None:
        raise ValueError("Заполните KEITARO в .env")
    defaults = settings.campaign_creation or CampaignCreationDefaults(
        domain_id=args.domain_id,
        group_id=args.group_id,
        traffic_source_id=args.source_id,
    )
    schema = "verification_" + uuid4().hex
    admin = create_async_engine(url)
    manager = AsyncDatabaseSessionManager(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    request = CreateCampaignDTO(
        request_id=args.request_id,
        name="[TEST] Adrobot service verification",
        country_code="AU",
        offer_id=args.offer_id,
    )
    async with admin.begin() as connection:
        await connection.execute(CreateSchema(schema))
    try:
        async with manager.engine.begin() as connection:
            await connection.run_sync(migrate)
        async with HttpKeitaroGateway(settings.keitaro) as gateway:

            def factory() -> StreamUnitOfWorkSQLAlchemy:
                return StreamUnitOfWorkSQLAlchemy(manager)

            creator = CampaignCreationService(factory, gateway, defaults)
            try:
                result = await creator.create_campaign(request)
                print("Created:", result.model_dump(mode="json"), flush=True)
                assert result == await creator.create_campaign(request)
                assert (
                    await gateway.get_campaign(result.campaign_id)
                ).state == "active"
                sync = CampaignSyncService(factory, gateway)
                fetched = await sync.fetch_campaign(result.campaign_id)
                assert len(fetched.streams) == 2
                target = next(
                    row
                    for row in fetched.streams
                    if row.stream.keitaro_stream_id == result.offers_stream_id
                )
                geo_before = (
                    await gateway.get_stream(result.geo_stream_id)
                ).raw_payload
                draft = target.draft
                async with factory() as uow:
                    editor = StreamDraftService(uow.drafts, gateway)
                    draft = await editor.add_offer(
                        draft.id,
                        args.additional_offer_id,
                        expected_revision=draft.revision,
                    )
                    draft = await editor.pin_share(
                        draft.id, args.offer_id, 70, expected_revision=draft.revision
                    )
                    await uow.commit()
                draft = await sync.push_stream(
                    draft.id, expected_revision=draft.revision
                )
                assert not draft.is_dirty
                remote = await gateway.get_stream(result.offers_stream_id)
                assert {row.offer_id: row.share for row in remote.offers} == {
                    args.offer_id: 70,
                    args.additional_offer_id: 30,
                }
                assert draft == await sync.push_stream(
                    draft.id, expected_revision=draft.revision
                )
                async with factory() as uow:
                    editor = StreamDraftService(uow.drafts, gateway)
                    draft = await editor.remove_offer(
                        draft.id, args.offer_id, expected_revision=draft.revision
                    )
                    draft = await editor.cancel_changes(
                        draft.id, expected_revision=draft.revision
                    )
                    assert not draft.is_dirty
                    draft = await editor.unpin_share(
                        draft.id, args.offer_id, expected_revision=draft.revision
                    )
                    draft = await editor.remove_offer(
                        draft.id,
                        args.additional_offer_id,
                        expected_revision=draft.revision,
                    )
                    await uow.commit()
                draft = await sync.push_stream(
                    draft.id, expected_revision=draft.revision
                )
                remote = await gateway.get_stream(result.offers_stream_id)
                assert [(row.offer_id, row.share) for row in remote.offers] == [
                    (args.offer_id, 100)
                ]
                assert any(
                    not row.is_active
                    and row.keitaro_offer_id == args.additional_offer_id
                    for row in draft.offers
                )
                assert (
                    await gateway.get_stream(result.geo_stream_id)
                ).raw_payload == geo_before
                print(
                    "Passed: create, repeat, Fetch, add, pin, Push, "
                    "repeat Push, Cancel, remove, Push; GEO unchanged",
                    flush=True,
                )
            finally:
                attempt = await creator.get_attempt(request.request_id)
                if attempt is not None and attempt.campaign_id is not None:
                    disabled = await gateway.set_campaign_state(
                        attempt.campaign_id, active=False
                    )
                    assert disabled.state == "disabled"
                    print("Test campaign disabled:", disabled.id, flush=True)
    finally:
        await manager.shutdown()
        try:
            async with admin.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await admin.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Создать отдельную тестовую кампанию, проверить сервисы и выключить её. "
            "Локальная тестовая схема удаляется."
        )
    )
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--request-id", type=UUID, default=uuid4())
    parser.add_argument("--domain-id", type=int)
    parser.add_argument("--group-id", type=int)
    parser.add_argument("--source-id", type=int)
    parser.add_argument("--offer-id", type=int, required=True)
    parser.add_argument("--additional-offer-id", type=int, required=True)
    args = parser.parse_args()
    if args.offer_id == args.additional_offer_id:
        parser.error("Для проверки нужны два разных оффера")
    asyncio.run(verify(args))


if __name__ == "__main__":
    main()
