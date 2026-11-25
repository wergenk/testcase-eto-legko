import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from alembic import command
from src.infrastructure.database import AsyncDatabaseSessionManager


def migrate(connection: Connection) -> None:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def manager() -> AsyncIterator[AsyncDatabaseSessionManager]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to an isolated PostgreSQL test database")
    if not (make_url(url).database or "").startswith("adrobot_test"):
        raise ValueError("Repository tests require a database named adrobot_test*")
    schema = "test_repositories_" + uuid4().hex
    admin_engine = create_async_engine(url)
    session_manager = AsyncDatabaseSessionManager(
        url, connect_args={"server_settings": {"search_path": schema}}
    )
    async with admin_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    try:
        async with session_manager.engine.begin() as connection:
            await connection.run_sync(migrate)
        yield session_manager
    finally:
        await session_manager.shutdown()
        try:
            async with admin_engine.begin() as connection:
                await connection.execute(DropSchema(schema, cascade=True))
        finally:
            await admin_engine.dispose()
