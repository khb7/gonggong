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


def test_select_center_offset_safe():
    """safe 전략은 +MAD를 반환해야 한다."""
    mad_val = Decimal("0.005")
    assert select_center_offset("safe", mad_val) == Decimal("0.005")


def test_select_center_offset_normal():
    """normal 전략은 0을 반환해야 한다."""
    assert select_center_offset("normal", Decimal("0.005")) == Decimal("0")


def test_select_center_offset_aggressive():
    """aggressive 전략은 -MAD를 반환해야 한다."""
    mad_val = Decimal("0.005")
    assert select_center_offset("aggressive", mad_val) == Decimal("-0.005")


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
