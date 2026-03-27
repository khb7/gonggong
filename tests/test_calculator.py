"""
tests/test_calculator.py
calculator.py 단위 테스트
"""

import pytest
from decimal import Decimal
from app.engine.calculator import calculate_single, calculate_bid_spread


# ──────────────────────────────────────────
# calculate_single 테스트
# ──────────────────────────────────────────

def test_calculate_single_basic():
    """
    LLR=0.87745, offset=0 → combined=0.87745 → digit_filter Triggered (no Shift)
    1,000,000,000 × 1.0 × 0.87745 = 877,450,000원
    """
    result = calculate_single(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87745"),
        predicted_rate=Decimal("1.00000"),
        offset=Decimal("0"),
    )
    # 0.87745+0=0.87745 → 745 블랙 발동(기록만 함, 값 유지)
    assert result["price_krw"] == 877_450_000
    assert result["digit_filter_triggered"] is True


def test_calculate_single_clean_combined_rate():
    """
    LLR=0.87800, offset=0 → combined=0.87800 → 800은 블랙 상했의 없으므로 그대로.
    1,000,000,000 × 1.0 × 0.87800 = 878,000,000원
    """
    result = calculate_single(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87800"),
        predicted_rate=Decimal("1.00000"),
        offset=Decimal("0"),
    )
    assert result["price_krw"] == 878_000_000
    assert result["digit_filter_triggered"] is False


def test_calculate_single_with_positive_offset():
    """
    LLR=0.87800, offset=+0.001 → combined=0.87900 → 900은 안전.
    1,000,000,000 × 1.0 × 0.87900 = 879,000,000원
    """
    result = calculate_single(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87800"),
        predicted_rate=Decimal("1.00000"),
        offset=Decimal("0.001"),
    )
    assert result["price_krw"] == 879_000_000


def test_calculate_single_with_negative_offset():
    """
    LLR=0.87800, offset=-0.001 → combined=0.87700 → 700은 안전.
    1,000,000,000 × 1.0 × 0.87700 = 877,000,000원
    """
    result = calculate_single(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87800"),
        predicted_rate=Decimal("1.00000"),
        offset=Decimal("-0.001"),
    )
    assert result["price_krw"] == 877_000_000


def test_calculate_single_price_rounds_down():
    """원화는 소수점 이하 버림(ROUND_DOWN)을 적용해야 한다."""
    result = calculate_single(
        base_price=100_000_000,
        lower_limit_rate=Decimal("0.87800"),
        predicted_rate=Decimal("0.99000"),
        offset=Decimal("0"),
    )
    assert isinstance(result["price_krw"], int)
    # 100,000,000 × 0.99 × 0.87800 = 86,922,000 (정수)
    assert result["price_krw"] == 86_922_000


# ──────────────────────────────────────────
# calculate_bid_spread 테스트
# ──────────────────────────────────────────

def test_calculate_bid_spread_returns_correct_count():
    """count=1이면 bids 리스트가 1개여야 한다."""
    result = calculate_bid_spread(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87745"),
        predicted_rate=Decimal("1.00000"),
        participants=152,
        mad_val=Decimal("0.002"),
        count=1,
    )
    assert len(result["bids"]) == 1


def test_calculate_bid_spread_normal_strategy():
    """participants=152 이라도 항상 'aggressive' 전략이어야 한다."""
    result = calculate_bid_spread(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87745"),
        predicted_rate=Decimal("1.00000"),
        participants=152,
        mad_val=Decimal("0.002"),
    )
    assert result["strategy"] == "aggressive"


def test_calculate_bid_spread_safe_strategy():
    """participants=30 이라도 항상 'aggressive' 전략이어야 한다."""
    result = calculate_bid_spread(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87745"),
        predicted_rate=Decimal("1.00000"),
        participants=30,
        mad_val=Decimal("0.002"),
    )
    assert result["strategy"] == "aggressive"


def test_calculate_bid_spread_digit_filter_applied_flag():
    """
    LLR=0.87745일 때 combined_rate에 745 블랙채 마커는 digit_filter_applied로 확인.
    """
    result = calculate_bid_spread(
        base_price=1_000_000_000,
        lower_limit_rate=Decimal("0.87745"),
        predicted_rate=Decimal("1.00000"),
        participants=152,
        mad_val=Decimal("0.002"),
    )
    # bids 중 하나라도 digit_filter_triggered 키가 존재해야 한다
    for bid in result["bids"]:
        assert "digit_filter_triggered" in bid
