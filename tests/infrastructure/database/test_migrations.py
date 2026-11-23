import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import insert, inspect, text, update
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from alembic import command
from src.infrastructure.database.models import (
    BaseORM,
    DraftOfferORM,
    StreamDraftORM,
    StreamORM,
    StreamSnapshotORM,
)

pytestmark = pytest.mark.asyncio


def migrate(connection: Connection, *, downgrade: bool = False) -> None:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    if downgrade:
        command.downgrade(config, "base")
    else:
        command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncConnection]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL test database")
    if not (make_url(url).database or "").startswith("adrobot_test"):
        raise ValueError("Integration tests require a database named adrobot_test*")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(migrate)
                yield connection
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded(db: AsyncConnection) -> AsyncConnection:
    await db.execute(
        insert(StreamORM),
        [
            {"id": 1, "keitaro_stream_id": 10, "keitaro_campaign_id": 20, "name": "A"},
            {"id": 2, "keitaro_stream_id": 11, "keitaro_campaign_id": 20, "name": "B"},
        ],
    )
    await db.execute(
        insert(StreamSnapshotORM),
        [
            {"id": 1, "stream_id": 1, "payload": {"offers": []}},
            {"id": 2, "stream_id": 2, "payload": {"offers": []}},
        ],
    )
    await db.execute(
        insert(StreamDraftORM),
        {"id": 1, "stream_id": 1, "base_snapshot_id": 1, "base_editor_state": []},
    )
    return db


async def test_upgrade_matches_models_and_downgrade_round_trip(
    db: AsyncConnection,
) -> None:
    def compare(connection: Connection) -> list:
        return compare_metadata(
            MigrationContext.configure(connection), BaseORM.metadata
        )

    assert await db.run_sync(compare) == []
    await db.run_sync(lambda connection: migrate(connection, downgrade=True))
    tables = await db.run_sync(lambda connection: inspect(connection).get_table_names())
    assert not set(BaseORM.metadata.tables).intersection(tables)
    await db.run_sync(migrate)
    assert await db.run_sync(compare) == []


async def test_snapshot_cannot_belong_to_another_stream(
    seeded: AsyncConnection,
) -> None:
    with pytest.raises(IntegrityError):
        async with seeded.begin_nested():
            await seeded.execute(
                insert(StreamDraftORM),
                {
                    "id": 2,
                    "stream_id": 2,
                    "base_snapshot_id": 1,
                    "base_editor_state": [],
                },
            )


async def test_one_draft_per_stream(seeded: AsyncConnection) -> None:
    with pytest.raises(IntegrityError):
        async with seeded.begin_nested():
            await seeded.execute(
                insert(StreamDraftORM),
                {
                    "id": 2,
                    "stream_id": 1,
                    "base_snapshot_id": 1,
                    "base_editor_state": [],
                },
            )


async def test_snapshot_is_immutable(seeded: AsyncConnection) -> None:
    with pytest.raises(DBAPIError, match="immutable"):
        async with seeded.begin_nested():
            await seeded.execute(
                update(StreamSnapshotORM)
                .where(StreamSnapshotORM.id == 1)
                .values(payload={"offers": [999]})
            )


@pytest.mark.parametrize(
    "invalid",
    [
        {"share": -1},
        {"share": 101},
        {"position": -1},
        {"keitaro_offer_id": 0},
        {"is_active": False, "share": 10},
    ],
)
async def test_offer_constraints(
    seeded: AsyncConnection,
    invalid: dict[str, int | bool],
) -> None:
    values = {
        "draft_id": 1,
        "keitaro_offer_id": 100,
        "name": "Test",
        "share": 100,
        "position": 0,
        "is_active": True,
    } | invalid
    with pytest.raises(IntegrityError):
        async with seeded.begin_nested():
            await seeded.execute(insert(DraftOfferORM), values)


async def test_duplicate_offer_is_rejected(seeded: AsyncConnection) -> None:
    values = {
        "draft_id": 1,
        "keitaro_offer_id": 100,
        "name": "Test",
        "share": 100,
        "position": 0,
    }
    await seeded.execute(insert(DraftOfferORM), values)
    with pytest.raises(IntegrityError):
        async with seeded.begin_nested():
            await seeded.execute(insert(DraftOfferORM), values)


async def test_deleting_draft_removes_offer_rows_but_keeps_snapshot(
    seeded: AsyncConnection,
) -> None:
    await seeded.execute(
        insert(DraftOfferORM),
        {"draft_id": 1, "keitaro_offer_id": 100, "name": "Test", "position": 0},
    )
    await seeded.execute(text("DELETE FROM stream_drafts WHERE id = 1"))
    assert (
        await seeded.execute(text("SELECT count(*) FROM draft_offers"))
    ).scalar() == 0
    assert (
        await seeded.execute(text("SELECT count(*) FROM stream_snapshots"))
    ).scalar() == 2


async def test_defaults_and_json_round_trip(seeded: AsyncConnection) -> None:
    revision, baseline, created_at = (
        await seeded.execute(
            text("SELECT revision, base_editor_state, created_at FROM stream_drafts")
        )
    ).one()
    assert revision == 1
    assert baseline == []
    assert created_at.tzinfo is not None
