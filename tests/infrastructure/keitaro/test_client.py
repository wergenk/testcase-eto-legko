from copy import deepcopy

import httpx
import pytest

from src.config import KeitaroSettings
from src.core.dto import KeitaroStreamOfferInputDTO
from src.core.exceptions import (
    KeitaroAuthorizationError,
    KeitaroError,
    KeitaroNotFoundError,
    KeitaroTimeoutError,
)
from src.infrastructure.keitaro import HttpKeitaroGateway

pytestmark = pytest.mark.asyncio


@pytest.fixture
def settings() -> KeitaroSettings:
    return KeitaroSettings(
        base_url="https://keitaro.example/admin_api/v1",
        api_key="test-api-key",
        timeout_seconds=2,
    )


@pytest.fixture
def stream_payload() -> dict:
    return {
        "id": 42,
        "campaign_id": 7,
        "name": "Offers",
        "schema": "landings",
        "filters": [{"name": "country", "mode": "reject", "payload": ["AU"]}],
        "landings": [],
        "action_options": {"redirect_type": "http"},
        "offers": [
            {
                "id": 91,
                "stream_id": 42,
                "offer_id": 10,
                "share": 100,
                "state": "active",
                "created_at": "2026-11-24",
            },
        ],
    }


async def test_campaign_streams_preserve_raw_payload_and_extra_fields(
    settings: KeitaroSettings,
    stream_payload: dict,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert (
            str(request.url)
            == "https://keitaro.example/admin_api/v1/campaigns/7/streams"
        )
        assert request.headers["Api-Key"] == "test-api-key"
        assert request.headers["Accept"] == "application/json"
        assert request.extensions["timeout"]["read"] == 2
        return httpx.Response(200, json=[stream_payload])

    async with HttpKeitaroGateway(
        settings, transport=httpx.MockTransport(handler)
    ) as api:
        streams = await api.get_campaign_streams(7)

    assert len(streams) == 1
    stream = streams[0]
    assert stream.id == 42 and stream.campaign_id == 7
    assert stream.offers[0].offer_id == 10 and stream.offers[0].share == 100
    assert stream.raw_payload == stream_payload
    assert "filters" in stream.raw_payload
    assert stream.raw_payload is not stream_payload


@pytest.mark.parametrize("include_offers", [False, True])
async def test_redirect_stream_without_offers_is_not_discarded(
    settings: KeitaroSettings,
    include_offers: bool,
) -> None:
    payload = {
        "id": 43,
        "campaign_id": 7,
        "name": "GEO to Google",
        "action_payload": "https://www.google.com/",
        "filters": [{"unknown": True}],
    }
    if include_offers:
        payload["offers"] = []
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with HttpKeitaroGateway(settings, transport=transport) as api:
        stream = await api.get_stream(43)
    assert stream.offers == ()
    assert stream.raw_payload == payload


async def test_empty_existing_campaign(
    settings: KeitaroSettings,
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    async with HttpKeitaroGateway(settings, transport=transport) as api:
        assert await api.get_campaign_streams(7) == []
        assert await api.list_offers() == []


async def test_offer_catalog_and_single_offer_ignore_tracker_only_fields(
    settings: KeitaroSettings,
) -> None:
    payload = {"id": 10, "name": "Test offer", "state": "active", "payout_value": 99}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/offers"):
            return httpx.Response(200, json=[payload])
        assert request.url.path.endswith("/offers/10")
        return httpx.Response(200, json=payload)

    async with HttpKeitaroGateway(
        settings, transport=httpx.MockTransport(handler)
    ) as api:
        offers = await api.list_offers()
        offer = await api.get_offer(10)
    assert offers == [offer]
    assert offer.model_dump() == {"id": 10, "name": "Test offer", "state": "active"}


@pytest.mark.parametrize("empty", [False, True])
async def test_put_only_replaces_offers_and_uses_server_response(
    settings: KeitaroSettings,
    stream_payload: dict,
    empty: bool,
) -> None:
    offers = [] if empty else [KeitaroStreamOfferInputDTO(offer_id=20, share=100)]
    expected = {"offers": [offer.model_dump(mode="json") for offer in offers]}
    returned = deepcopy(stream_payload)
    returned["name"] = "Name from server"
    returned["offers"] = expected["offers"]

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        assert request.method == "PUT"
        assert request.url.path == "/admin_api/v1/streams/42"
        assert json.loads(request.content) == expected
        return httpx.Response(200, json=returned)

    async with HttpKeitaroGateway(
        settings, transport=httpx.MockTransport(handler)
    ) as api:
        result = await api.replace_stream_offers(42, offers)
    assert result.name == "Name from server"
    assert result.raw_payload["filters"] == stream_payload["filters"]
    assert [offer.offer_id for offer in result.offers] == ([] if empty else [20])


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, KeitaroAuthorizationError),
        (403, KeitaroAuthorizationError),
        (404, KeitaroNotFoundError),
        (400, KeitaroError),
        (402, KeitaroError),
        (429, KeitaroError),
        (500, KeitaroError),
    ],
)
async def test_http_errors_are_mapped_without_exposing_response(
    settings: KeitaroSettings,
    status: int,
    error_type: type[KeitaroError],
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": "test-api-key"})
    )
    async with HttpKeitaroGateway(settings, transport=transport) as api:
        with pytest.raises(error_type) as raised:
            await api.get_stream(42)
    assert "test-api-key" not in str(raised.value)


async def test_missing_campaign_does_not_look_like_empty_campaign(
    settings: KeitaroSettings,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(404, json={"error": "Missing"})
    )
    async with HttpKeitaroGateway(settings, transport=transport) as api:
        with pytest.raises(KeitaroNotFoundError):
            await api.get_campaign_streams(999)


@pytest.mark.parametrize("error_type", [httpx.ReadTimeout, httpx.ConnectError])
async def test_transport_errors_are_mapped_and_write_is_not_retried(
    settings: KeitaroSettings,
    error_type: type[httpx.RequestError],
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise error_type("test-api-key", request=request)

    expected = KeitaroTimeoutError if error_type is httpx.ReadTimeout else KeitaroError
    async with HttpKeitaroGateway(
        settings, transport=httpx.MockTransport(handler)
    ) as api:
        with pytest.raises(expected) as raised:
            await api.replace_stream_offers(42, [])
    assert len(calls) == 1
    assert "test-api-key" not in str(raised.value)


async def test_redirect_is_not_followed_and_key_is_not_sent_elsewhere(
    settings: KeitaroSettings,
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://other.example/"})

    async with HttpKeitaroGateway(
        settings, transport=httpx.MockTransport(handler)
    ) as api:
        with pytest.raises(KeitaroError, match="302"):
            await api.list_offers()
    assert len(calls) == 1


@pytest.mark.parametrize("content", [b"<html>Login</html>", b"", b"{invalid}"])
async def test_non_json_response_is_rejected(
    settings: KeitaroSettings,
    content: bytes,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=content)
    )
    async with HttpKeitaroGateway(settings, transport=transport) as api:
        with pytest.raises(KeitaroError, match="JSON"):
            await api.list_offers()


@pytest.mark.parametrize("payload", [None, {}, {"id": 1}, [{"id": "bad"}]])
async def test_invalid_response_shape_is_rejected(
    settings: KeitaroSettings,
    payload: object,
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    async with HttpKeitaroGateway(settings, transport=transport) as api:
        with pytest.raises(KeitaroError):
            await api.get_campaign_streams(7)


@pytest.mark.parametrize("value", [0, -1, True, "42", 42.5])
async def test_invalid_id_is_rejected_before_request(
    settings: KeitaroSettings,
    value: object,
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    async with HttpKeitaroGateway(
        settings, transport=httpx.MockTransport(handler)
    ) as api:
        with pytest.raises(ValueError):
            await api.get_stream(value)
    assert calls == []


async def test_client_is_closed_on_context_exit_and_exception_propagates(
    settings: KeitaroSettings,
) -> None:
    api = HttpKeitaroGateway(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    with pytest.raises(RuntimeError, match="User error"):
        async with api:
            raise RuntimeError("User error")
    with pytest.raises(RuntimeError, match="closed"):
        await api.list_offers()
