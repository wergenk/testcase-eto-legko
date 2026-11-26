from fastapi import APIRouter

from src.api.routers import campaigns_router, drafts_router, offers_router
from src.api.schemas.common import ErrorResponse

router = APIRouter(
    responses={
        404: {"model": ErrorResponse, "description": "Объект не найден"},
        409: {"model": ErrorResponse, "description": "Конфликт версии или состояния"},
        422: {"model": ErrorResponse, "description": "Неверные данные или действие"},
        502: {"model": ErrorResponse, "description": "Ошибка Keitaro"},
        503: {"model": ErrorResponse, "description": "БД или настройки недоступны"},
        504: {"model": ErrorResponse, "description": "Таймаут Keitaro"},
    }
)
router.include_router(campaigns_router, prefix="/api/campaigns")
router.include_router(drafts_router, prefix="/api/drafts")
router.include_router(offers_router, prefix="/api/offers")


@router.get("/health", tags=["system"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
