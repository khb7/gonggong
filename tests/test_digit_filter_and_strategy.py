"""
tests/test_digit_filter_and_strategy.py
digit_filter.py / strategy.py 단위 테스트
"""

import pytest
from decimal import Decimal
from app.engine.digit_filter import apply_digit_filter, DIGIT_BLACKLIST
from app.engine.strategy import select_strategy, select_center_offset, generate_bid_spread


# ──────────────────────────────────────────
# digit_filter 테스트
# ──────────────────────────────────────────

def test_digit_filter_blacklist_745():
    """
    끝자리 745 → +0.001 Shift → 0.87745 + 0.001 = 0.87845
    Shift 후 845는 블랙리스트 없으므로 최종 반환.
    """
    rate = Decimal("0.87745")
    result, shifted = apply_digit_filter(rate)
    assert result == Decimal("0.87845")
    assert shifted is True


def test_digit_filter_blacklist_000():
    """
    끝자리 000 → +0.001 Shift → 0.87000 + 0.001 = 0.87100
    100은 블랙리스트 없으므로 최종 반환.
    """
    rate = Decimal("0.87000")
    result, shifted = apply_digit_filter(rate)
    assert result == Decimal("0.87100")
    assert shifted is True


def test_digit_filter_blacklist_500():
    """0.87500 + 0.001 = 0.87600, 600은 안전."""
    rate = Decimal("0.87500")
    result, shifted = apply_digit_filter(rate)
    assert result == Decimal("0.87600")
    assert shifted is True


def test_digit_filter_blacklist_777():
    """0.87777 + 0.001 = 0.87877, 877은 안전."""
    rate = Decimal("0.87777")
    result, shifted = apply_digit_filter(rate)
    assert result == Decimal("0.87877")
    assert shifted is True


def test_digit_filter_safe_value_unchanged():
    """블랙리스트에 없는 값은 그대로 반환되어야 한다."""
    rate = Decimal("0.87746")
    result, shifted = apply_digit_filter(rate)
    assert result == rate
    assert shifted is False


def test_digit_filter_no_float_ambiguity():
    """
    float 0.745는 내부적으로 0.7450000000000001이 될 수 있다.
    Decimal 문자열 방식은 이 오차와 무관하게 정확히 동작해야 한다.
    """
    # Decimal("0.745")는 정확히 "745" 끝자리를 가짐
    rate = Decimal("0.745")
    result, shifted = apply_digit_filter(rate)
    assert shifted is True


# ──────────────────────────────────────────
# strategy 테스트
# ──────────────────────────────────────────

@pytest.mark.parametrize("participants, expected", [
    (10,  "aggressive"),
    (49,  "aggressive"),
    (50,  "aggressive"),
    (152, "aggressive"),
    (299, "aggressive"),
    (300, "aggressive"),
    (500, "aggressive"),
])
def test_select_strategy(participants, expected):
    """경쟁자 수에 무관하게 항상 aggressive 전략이어야 한다."""
    assert select_strategy(participants) == expected


def test_select_center_offset_is_always_zero():
    """중심 offset 은 전략·MAD 와 무관하게 0 이다.

    offset 0 = "가정한 사정률에서의 낙찰하한가에 정확히 붙인다".

    예전에는 safe/aggressive 가 +MAD(0.486%p)를 돌려줬다. 유효하기는 하지만
    이길 자리가 아니다 — 실측 12,010 공고에서 낙찰자는 하한가 위 +0.016%
    (중앙값)에 붙어 있고, 0.486%p 는 그보다 30배 멀다.

    위험 조절은 offset 이 아니라 사정률(FIXED_PREPRICE_RATE)로 한다.
    유효/무효를 가르는 건 `c >= 실제사정률` 이라 offset 을 올리면
    c 를 올리는 것과 효과가 겹치면서 낙찰선에서만 멀어진다.
    """
    for strategy in ("safe", "normal", "aggressive"):
        for mad in (Decimal("0"), Decimal("0.005"), Decimal("0.05")):
            assert select_center_offset(strategy, mad) == Decimal("0"), (
                f"{strategy} / MAD {mad} 에서 0 이 아니다"
            )


def test_center_offset_never_goes_below_the_floor():
    """음수 offset 은 하한가 미달 = 실격이므로 절대 나오면 안 된다."""
    assert select_center_offset("aggressive", Decimal("0.05")) >= Decimal("0")


def test_select_center_offset_never_negative():
    """어떤 전략이든 음수 offset을 내지 않는다 (하한 미달 = 실격)."""
    mad_val = Decimal("0.005")
    for strategy in ("safe", "normal", "aggressive", "알 수 없는 전략"):
        assert select_center_offset(strategy, mad_val) >= Decimal("0")


def test_generate_bid_spread_count():
    """count=1이면 1개의 후보를 반환해야 한다."""
    result = generate_bid_spread(center=Decimal("0.0"), count=1)
    assert len(result) == 1


def test_generate_bid_spread_values():
    """중심 0.0, step=0.001, count=1 → [0.000]
    digit_filter는 calculator로 위임하므로 offset 자체 값을 검증.
    """
    result = generate_bid_spread(
        center=Decimal("0.0"),
        step=Decimal("0.001"),
        count=1,
    )
    assert result[0] == Decimal("0.000")
