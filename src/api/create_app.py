from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.exceptions import register_exception_handlers
from src.api.router import router
from src.config import Settings, get_settings
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.keitaro import HttpKeitaroGateway


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = app.state.settings
    manager = AsyncDatabaseSessionManager(settings.db.url)
    gateway = HttpKeitaroGateway(settings.keitaro) if settings.keitaro else None
    app.state.session_manager = manager
    app.state.keitaro = gateway
    try:
        yield
    finally:
        try:
            if gateway is not None:
                await gateway.aclose()
        finally:
            await manager.shutdown()
            app.state.session_manager = None
            app.state.keitaro = None


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="Adrobot", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings if settings is not None else get_settings()
    app.state.session_manager = None
    app.state.keitaro = None
    register_exception_handlers(app)
    app.include_router(router)
    return app
