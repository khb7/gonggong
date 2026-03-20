"""
tests/test_statistics.py
statistics.py 단위 테스트
"""

import pytest
from decimal import Decimal
from app.engine.statistics import trimmed_median, mad, confidence_range


# ──────────────────────────────────────────
# trimmed_median 테스트
# ──────────────────────────────────────────

def test_trimmed_median_basic():
    """극단값 2개가 제거되고 나머지의 중앙값이 반환되어야 한다."""
    rates = [Decimal(v) for v in ["0.50", "0.99", "1.00", "1.01", "1.50"]]
    result = trimmed_median(rates, trim_pct=0.05)
    assert result == Decimal("1.00")


def test_trimmed_median_all_same():
    """모든 값이 동일하면 그 값이 반환되어야 한다."""
    rates = [Decimal("1.00")] * 10
    assert trimmed_median(rates) == Decimal("1.00")


def test_trimmed_median_even_count():
    """짝수 개 데이터는 중간 두 값의 평균을 반환해야 한다."""
    rates = [Decimal(v) for v in ["1.00", "1.02", "1.04", "1.06"]]
    result = trimmed_median(rates, trim_pct=0.0)
    assert result == Decimal("1.03")


def test_trimmed_median_empty_raises():
    """빈 리스트는 ValueError를 발생시켜야 한다."""
    with pytest.raises(ValueError):
        trimmed_median([])


def test_trimmed_median_too_aggressive_trim_raises():
    """trim이 너무 커서 데이터가 모두 제거되면 ValueError를 발생시켜야 한다."""
    rates = [Decimal("1.00"), Decimal("1.01")]
    with pytest.raises(ValueError):
        trimmed_median(rates, trim_pct=0.6)


# ──────────────────────────────────────────
# mad 테스트
# ──────────────────────────────────────────

def test_mad_basic():
    """MAD가 정확히 계산되어야 한다."""
    # Median = 1.00, 편차 = [0.01, 0.00, 0.01, 0.005] → MAD = 0.005
    rates = [Decimal(v) for v in ["1.00", "1.01", "0.99", "1.005"]]
    result = mad(rates)
    assert result == Decimal("0.005")


def test_mad_all_same_is_zero():
    """모든 값이 동일하면 MAD는 0이어야 한다."""
    rates = [Decimal("1.00")] * 5
    assert mad(rates) == Decimal("0")


def test_mad_empty_raises():
    """빈 리스트는 ValueError를 발생시켜야 한다."""
    with pytest.raises(ValueError):
        mad([])


# ──────────────────────────────────────────
# confidence_range 테스트
# ──────────────────────────────────────────

def test_confidence_range():
    """신뢰 범위가 [Median - MAD, Median + MAD]로 정확히 반환되어야 한다."""
    median = Decimal("1.00")
    mad_val = Decimal("0.01")
    lower, upper = confidence_range(median, mad_val)
    assert lower == Decimal("0.99")
    assert upper == Decimal("1.01")
