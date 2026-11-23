import pytest
from pydantic import ValidationError

from src.core.dto import DraftOfferDTO
from src.core.exceptions import OfferShareError
from src.core.services import recalculate_offer_shares


def make_offer(
    offer_id: int,
    *,
    share: int = 0,
    pinned: bool = False,
    active: bool = True,
    position: int = 0,
) -> DraftOfferDTO:
    return DraftOfferDTO(
        keitaro_offer_id=offer_id,
        name=f"Offer {offer_id}",
        share=share,
        is_pinned=pinned,
        is_active=active,
        position=position,
    )


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, [100]), (2, [50, 50]), (3, [34, 33, 33]), (4, [25, 25, 25, 25])],
)
def test_equal_distribution(count: int, expected: list[int]) -> None:
    offers = [make_offer(index + 1) for index in range(count)]

    result = recalculate_offer_shares(offers)

    assert [offer.share for offer in result] == expected


def test_pinned_share_is_preserved_and_remainder_is_distributed() -> None:
    offers = [
        make_offer(1, share=25, pinned=True),
        make_offer(2),
        make_offer(3),
    ]

    result = recalculate_offer_shares(offers)

    assert [offer.share for offer in result] == [25, 38, 37]


def test_remainder_uses_position_then_id_without_reordering_rows() -> None:
    offers = [
        make_offer(30, position=2),
        make_offer(20, position=1),
        make_offer(10, position=1),
    ]

    result = recalculate_offer_shares(offers)
    reversed_result = recalculate_offer_shares(list(reversed(offers)))

    assert [offer.keitaro_offer_id for offer in result] == [30, 20, 10]
    assert [offer.share for offer in result] == [33, 33, 34]
    assert {offer.keitaro_offer_id: offer.share for offer in result} == {
        offer.keitaro_offer_id: offer.share for offer in reversed_result
    }


def test_archived_pinned_offer_does_not_reserve_traffic() -> None:
    offers = [
        make_offer(1, share=90, pinned=True, active=False),
        make_offer(2),
        make_offer(3),
    ]

    result = recalculate_offer_shares(offers)

    assert [offer.share for offer in result] == [0, 50, 50]
    assert result[0].is_pinned
    assert not result[0].is_active


def test_empty_draft_is_allowed() -> None:
    assert recalculate_offer_shares([]) == ()


def test_archive_only_draft_is_allowed() -> None:
    result = recalculate_offer_shares(
        [make_offer(1, share=70, active=False), make_offer(2, active=False)]
    )

    assert len(result) == 2
    assert [offer.share for offer in result] == [0, 0]


@pytest.mark.parametrize("shares", [(60, 50), (20, 30), (0, 0)])
def test_impossible_pinned_shares_raise_domain_error(
    shares: tuple[int, int],
) -> None:
    offers = [
        make_offer(1, share=shares[0], pinned=True),
        make_offer(2, share=shares[1], pinned=True),
    ]

    with pytest.raises(OfferShareError):
        recalculate_offer_shares(offers)


def test_pinned_overflow_with_unpinned_offers_raises_domain_error() -> None:
    offers = [
        make_offer(1, share=60, pinned=True),
        make_offer(2, share=50, pinned=True),
        make_offer(3),
    ]

    with pytest.raises(OfferShareError):
        recalculate_offer_shares(offers)


def test_all_pinned_shares_totaling_100_are_preserved() -> None:
    offers = [
        make_offer(1, share=25, pinned=True),
        make_offer(2, share=75, pinned=True),
    ]

    assert recalculate_offer_shares(offers) == tuple(offers)


def test_fully_reserved_traffic_leaves_zero_for_unpinned_offers() -> None:
    result = recalculate_offer_shares(
        [make_offer(1, share=100, pinned=True), make_offer(2, share=50)]
    )

    assert [offer.share for offer in result] == [100, 0]


def test_more_than_100_offers_still_total_100() -> None:
    result = recalculate_offer_shares([make_offer(index + 1) for index in range(101)])

    assert sum(offer.share for offer in result) == 100
    assert all(offer.share == 1 for offer in result[:100])
    assert result[-1].share == 0


def test_add_remove_and_restore_recalculate_active_shares() -> None:
    initial = recalculate_offer_shares([make_offer(1), make_offer(2), make_offer(3)])
    added = recalculate_offer_shares((*initial, make_offer(4)))
    removed = recalculate_offer_shares(
        (*added[:3], added[3].model_copy(update={"is_active": False}))
    )
    restored = recalculate_offer_shares(
        (*removed[:3], removed[3].model_copy(update={"is_active": True}))
    )

    assert [offer.share for offer in added] == [25, 25, 25, 25]
    assert [offer.share for offer in removed] == [34, 33, 33, 0]
    assert restored == added


def test_source_is_unchanged_and_recalculation_is_idempotent() -> None:
    offers = [make_offer(1, share=10), make_offer(2, share=30)]
    original = [offer.model_dump() for offer in offers]

    result = recalculate_offer_shares(offers)

    assert [offer.model_dump() for offer in offers] == original
    assert all(new is not old for new, old in zip(result, offers, strict=True))
    assert recalculate_offer_shares(result) == result
    for old, new in zip(offers, result, strict=True):
        assert old.model_dump(exclude={"share"}) == new.model_dump(exclude={"share"})


def test_duplicate_offer_id_including_archive_is_rejected() -> None:
    with pytest.raises(OfferShareError):
        recalculate_offer_shares([make_offer(1), make_offer(1, active=False)])


@pytest.mark.parametrize("share", [-1, 101, 25.5, True, "25"])
def test_draft_offer_rejects_invalid_or_non_integer_shares(share: object) -> None:
    with pytest.raises(ValidationError):
        DraftOfferDTO.model_validate(
            {
                "keitaro_offer_id": 1,
                "name": "Offer",
                "share": share,
                "is_pinned": False,
                "is_active": True,
                "position": 0,
            }
        )
