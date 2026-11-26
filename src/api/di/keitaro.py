from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from src.config import Settings
from src.core.interfaces import KeitaroGateway


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDepend = Annotated[Settings, Depends(get_app_settings)]


def get_keitaro_gateway(request: Request) -> KeitaroGateway:
    gateway = request.app.state.keitaro
    if gateway is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Подключение к Keitaro не настроено"
        )
    return gateway


KeitaroGatewayDepend = Annotated[KeitaroGateway, Depends(get_keitaro_gateway)]
