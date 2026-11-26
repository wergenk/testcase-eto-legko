from typing import Annotated

from fastapi import APIRouter, Query

from src.api.di.keitaro import KeitaroGatewayDepend
from src.api.schemas.common import PositiveID
from src.core.dto import KeitaroOfferDTO

router = APIRouter(tags=["offers"])


@router.get("", response_model=list[KeitaroOfferDTO])
async def list_offers(
    keitaro: KeitaroGatewayDepend,
    q: Annotated[str | None, Query(max_length=255)] = None,
    active_only: bool = False,
) -> list[KeitaroOfferDTO]:
    offers = await keitaro.list_offers()
    query = q.strip().casefold() if q else ""
    return [
        offer
        for offer in offers
        if (not active_only or offer.state == "active")
        and (not query or query in offer.name.casefold() or query in str(offer.id))
    ]


@router.get("/{offer_id}", response_model=KeitaroOfferDTO)
async def get_offer(
    offer_id: PositiveID, keitaro: KeitaroGatewayDepend
) -> KeitaroOfferDTO:
    return await keitaro.get_offer(offer_id)
