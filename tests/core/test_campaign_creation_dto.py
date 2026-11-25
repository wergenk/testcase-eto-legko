from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.core.dto.campaign_creation import CreateCampaignDTO


def test_normalize_creation_input() -> None:
    command = CreateCampaignDTO(
        request_id=uuid4(), name="  Campaign  ", country_code=" au ", offer_id=1
    )
    assert command.name == "Campaign"
    assert command.country_code == "AU"


@pytest.mark.parametrize("country", ["XX", "AAA", "A1", "", "UK"])
def test_reject_unknown_country(country: str) -> None:
    with pytest.raises(ValidationError):
        CreateCampaignDTO(
            request_id=uuid4(), name="Campaign", country_code=country, offer_id=1
        )


def test_reject_blank_name() -> None:
    with pytest.raises(ValidationError):
        CreateCampaignDTO(request_id=uuid4(), name="  ", country_code="AU", offer_id=1)
