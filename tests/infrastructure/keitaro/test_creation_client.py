import json

import httpx
import pytest

from src.config import KeitaroSettings
from src.core.dto.keitaro import KeitaroCampaignInputDTO, KeitaroStreamInputDTO
from src.core.exceptions import KeitaroError
from src.infrastructure.keitaro import HttpKeitaroGateway

pytestmark = pytest.mark.asyncio


async def test_list_campaigns_reads_all_pages_and_accepts_unset_domain() -> None:
    offsets = []

    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        count = 100 if offset == 0 else 1
        return httpx.Response(
            200,
            json=[
                {
                    "id": offset + index + 1,
                    "name": "Test",
                    "alias": str(offset + index),
                    "state": "active",
                    "domain_id": None,
                }
                for index in range(count)
            ],
        )

    async with HttpKeitaroGateway(
        settings(), transport=httpx.MockTransport(handler)
    ) as gateway:
        campaigns = await gateway.list_campaigns()
    assert offsets == [0, 100]
    assert len(campaigns) == 101
    assert campaigns[-1].id == 101
    assert "domain_id" not in campaigns[0].model_dump()


async def test_list_campaigns_rejects_repeated_page() -> None:
    page = [
        {"id": index + 1, "name": "Test", "alias": str(index), "state": "active"}
        for index in range(100)
    ]
    async with HttpKeitaroGateway(
        settings(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page)),
    ) as gateway:
        with pytest.raises(KeitaroError, match="страницу"):
            await gateway.list_campaigns()


def settings() -> KeitaroSettings:
    return KeitaroSettings(
        base_url="https://keitaro.example/admin_api/v1", api_key="test"
    )


def campaign() -> dict:
    return {
        "id": 10,
        "name": "Test",
        "alias": "test",
        "domain_id": 1,
        "group_id": 2,
        "traffic_source_id": 3,
        "state": "disabled",
        "type": "position",
    }


async def test_campaign_creation_and_activation_use_minimal_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        result = campaign()
        if request.method == "POST":
            assert request.url.path == "/admin_api/v1/campaigns"
            assert payload == {
                key: value for key, value in result.items() if key != "id"
            }
        else:
            assert request.method == "PUT"
            assert request.url.path == "/admin_api/v1/campaigns/10"
            assert payload == {"state": "active"}
            result["state"] = "active"
        return httpx.Response(200, json={**result, "extra": "ignored"})

    async with HttpKeitaroGateway(
        settings(), transport=httpx.MockTransport(handler)
    ) as gateway:
        created = await gateway.create_campaign(
            KeitaroCampaignInputDTO(
                **{key: value for key, value in campaign().items() if key != "id"}
            )
        )
        assert created.id == 10
        assert (
            await gateway.set_campaign_state(created.id, active=True)
        ).state == "active"


async def test_find_alias_reads_all_pages_without_parsing_unrelated_settings() -> None:
    pages = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/campaigns/10"):
            return httpx.Response(200, json=campaign())
        offset = int(request.url.params["offset"])
        pages.append(offset)
        if offset == 0:
            return httpx.Response(
                200,
                json=[
                    {"id": 100 + i, "alias": "other" + str(i), "domain_id": None}
                    for i in range(100)
                ],
            )
        return httpx.Response(200, json=[{"id": 10, "alias": "test"}])

    async with HttpKeitaroGateway(
        settings(), transport=httpx.MockTransport(handler)
    ) as gateway:
        assert (await gateway.find_campaign_by_alias("test")).id == 10
        assert pages == [0, 100]


async def test_repeated_campaign_page_does_not_loop() -> None:
    page = [{"id": i + 1, "alias": str(i)} for i in range(100)]
    async with HttpKeitaroGateway(
        settings(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=page)),
    ) as gateway:
        with pytest.raises(KeitaroError, match="страницу"):
            await gateway.find_campaign_by_alias("absent")


@pytest.mark.parametrize(
    "method,path,query",
    [
        ("list_domains", "domains", {}),
        ("list_campaign_groups", "groups", {"type": "campaigns"}),
        ("list_traffic_sources", "traffic_sources", {}),
    ],
)
async def test_creation_catalogs(method: str, path: str, query: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/admin_api/v1/" + path
        assert dict(request.url.params) == query
        return httpx.Response(200, json=[{"id": 1, "name": "Test"}])

    async with HttpKeitaroGateway(
        settings(), transport=httpx.MockTransport(handler)
    ) as gateway:
        assert [row.id for row in await getattr(gateway, method)()] == [1]


async def test_stream_creation_uses_wire_schema_and_country_accept() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/admin_api/v1/streams"
        payload = json.loads(request.content)
        assert payload["schema"] == "redirect"
        assert "stream_schema" not in payload
        assert payload["filter_or"] is False
        assert "filters_or" not in payload
        assert payload["filters"] == [
            {"name": "country", "mode": "accept", "payload": ["AU"]}
        ]
        return httpx.Response(200, json={"id": 20, **payload})

    async with HttpKeitaroGateway(
        settings(), transport=httpx.MockTransport(handler)
    ) as gateway:
        stream = await gateway.create_stream(
            KeitaroStreamInputDTO(
                campaign_id=10,
                name="GEO",
                type="regular",
                schema="redirect",
                position=1,
                action_payload="https://www.google.com/",
                filters=({"name": "country", "mode": "accept", "payload": ["AU"]},),
            )
        )
        assert stream.id == 20
