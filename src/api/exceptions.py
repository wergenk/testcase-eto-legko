from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from src.core.exceptions import (
    CampaignCreationConflictError,
    CampaignCreationError,
    DraftOfferError,
    KeitaroError,
    KeitaroNotFoundError,
    KeitaroTimeoutError,
    OfferShareError,
    StreamDraftConflictError,
    StreamDraftNotFoundError,
    StreamPublicationError,
)


async def not_found_handler(request: Request, exception: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exception)}
    )


async def conflict_handler(request: Request, exception: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": str(exception)}
    )


async def invalid_action_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exception)},
    )


async def upstream_error_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exception)}
    )


async def upstream_timeout_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT, content={"detail": str(exception)}
    )


async def database_error_handler(
    request: Request, exception: Exception
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "База данных временно недоступна"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StreamDraftNotFoundError, not_found_handler)
    app.add_exception_handler(KeitaroNotFoundError, not_found_handler)
    app.add_exception_handler(StreamDraftConflictError, conflict_handler)
    app.add_exception_handler(CampaignCreationConflictError, conflict_handler)
    app.add_exception_handler(DraftOfferError, invalid_action_handler)
    app.add_exception_handler(OfferShareError, invalid_action_handler)
    app.add_exception_handler(CampaignCreationError, invalid_action_handler)
    app.add_exception_handler(KeitaroError, upstream_error_handler)
    app.add_exception_handler(StreamPublicationError, upstream_error_handler)
    app.add_exception_handler(KeitaroTimeoutError, upstream_timeout_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
