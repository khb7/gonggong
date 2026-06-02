"""
tests/test_distribution.py
app/engine/distribution.py 단위 테스트

테스트 대상:
  - build_offset_distribution()
  - calc_my_position()
"""

import pytest
from decimal import Decimal
from app.engine.distribution import build_offset_distribution, calc_my_position


# ──────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────

def _row(bid_rate: str, lower_limit_rate: str, is_winner: bool) -> dict:
    return {
        "bid_rate": Decimal(bid_rate),
        "lower_limit_rate": Decimal(lower_limit_rate),
        "is_winner": is_winner,
    }


# ──────────────────────────────────────────
# build_offset_distribution
# ──────────────────────────────────────────

def test_build_distribution_single_bin():
    """같은 offset의 3건이 1개 bin으로 집계된다."""
    rows = [
        _row("0.87145", "0.87745", False),
        _row("0.87145", "0.87745", False),
        _row("0.87145", "0.87745", True),
    ]
    result = build_offset_distribution(rows)

    assert len(result) == 1
    assert result[0]["offset_pct"] == pytest.approx(-0.6, abs=0.05)
    assert result[0]["count"] == 3
    assert result[0]["win_count"] == 1


def test_build_distribution_multiple_bins():
    """다른 offset은 서로 다른 bin으로 분리된다."""
    rows = [
        _row("0.87145", "0.87745", False),  # offset = -0.006 → -0.6%
        _row("0.87145", "0.87745", False),
        _row("0.87245", "0.87745", True),   # offset = -0.005 → -0.5%
    ]
    result = build_offset_distribution(rows)

    assert len(result) == 2
    offsets = [b["offset_pct"] for b in result]
    assert pytest.approx(-0.6, abs=0.05) in offsets
    assert pytest.approx(-0.5, abs=0.05) in offsets


def test_build_distribution_sorted_by_offset():
    """결과는 offset_pct 오름차순으로 정렬된다."""
    rows = [
        _row("0.87745", "0.87745", False),  # 0.0%
        _row("0.87145", "0.87745", False),  # -0.6%
        _row("0.88245", "0.87745", False),  # +0.5%
    ]
    result = build_offset_distribution(rows)

    offsets = [b["offset_pct"] for b in result]
    assert offsets == sorted(offsets)


def test_build_distribution_empty_input():
    """빈 입력은 빈 리스트를 반환한다."""
    assert build_offset_distribution([]) == []


def test_build_distribution_no_winners():
    """낙찰자가 없는 경우 win_count는 0이다."""
    rows = [
        _row("0.87145", "0.87745", False),
        _row("0.87145", "0.87745", False),
    ]
    result = build_offset_distribution(rows)

    assert result[0]["win_count"] == 0
    assert result[0]["count"] == 2


def test_build_distribution_all_winners():
    """모두 낙찰자인 경우 win_count == count."""
    rows = [
        _row("0.87145", "0.87745", True),
        _row("0.87145", "0.87745", True),
    ]
    result = build_offset_distribution(rows)

    assert result[0]["win_count"] == 2
    assert result[0]["count"] == 2


def test_build_distribution_bins_close_together_stay_separate():
    """0.15% 차이 offset은 서로 다른 bin으로 분리된다."""
    rows = [
        _row("0.87145", "0.87745", False),  # -0.6%
        _row("0.87295", "0.87745", False),  # -0.45% → 다른 bin
    ]
    result = build_offset_distribution(rows)

    assert len(result) == 2


def test_build_distribution_different_lower_limit_rates():
    """lower_limit_rate가 다른 공고의 행들도 동일 offset으로 집계된다."""
    # 두 행의 LLR이 다르지만, bid_rate - LLR 결과가 같으면 같은 bin
    rows = [
        _row("0.87145", "0.87745", False),  # offset = -0.006
        _row("0.88145", "0.88745", False),  # offset = -0.006 (같은 offset)
    ]
    result = build_offset_distribution(rows)

    assert len(result) == 1
    assert result[0]["count"] == 2


# ──────────────────────────────────────────
# calc_my_position
# ──────────────────────────────────────────

def _make_distribution():
    """테스트용 3-bin 분포."""
    return [
        {"offset_pct": -1.0, "count": 100, "win_count": 5},
        {"offset_pct": -0.6, "count": 200, "win_count": 10},
        {"offset_pct": -0.3, "count": 100, "win_count": 3},
    ]


def test_calc_my_position_offset():
    """my_bid_price로 계산한 offset이 올바르게 반환된다."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    # offset = -0.006 → -0.6%
    my_bid = int(base_price * (float(llr) - 0.006))

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    assert pos["offset_pct"] == pytest.approx(-0.6, abs=0.1)


def test_calc_my_position_percentile():
    """내 offset보다 낮은 구간의 count 합 / 전체 count."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) - 0.006))  # offset ≈ -0.6%

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    # -1.0% bin (count=100)만 내 위치(-0.6%)보다 낮다
    # percentile = 100 / 400 * 100 = 25.0%
    assert pos["percentile"] == pytest.approx(25.0, abs=1.0)


def test_calc_my_position_historical_win_rate():
    """해당 bin의 win_count / count가 반환된다."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) - 0.006))  # offset ≈ -0.6%

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    # -0.6% bin: win_count=10, count=200 → 5.0%
    assert pos["historical_win_rate"] == pytest.approx(5.0, abs=0.1)
    assert pos["sample_count"] == 200


def test_calc_my_position_estimated_price():
    """estimated_price는 기초금액 × (하한율 + offset)으로 계산된다."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) - 0.006))

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    # offset_pct ≈ -0.6% → estimated_price = 100M × (0.87745 - 0.006)
    expected = int(base_price * (float(llr) - 0.006))
    assert abs(pos["estimated_price"] - expected) <= 1000  # 1천원 오차 허용


def test_calc_my_position_percentile_lowest():
    """가장 낮은 bin에 있는 경우 percentile은 0.0이다."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) - 0.010))  # offset = -1.0%

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    assert pos["percentile"] == pytest.approx(0.0, abs=1.0)


def test_calc_my_position_percentile_highest():
    """가장 높은 bin에 있는 경우 percentile은 (아래 bin 합 / 전체) × 100이다."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) - 0.003))  # offset = -0.3%

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    # -1.0%(100) + -0.6%(200) = 300 / 400 = 75%
    assert pos["percentile"] == pytest.approx(75.0, abs=1.0)


def test_calc_my_position_no_match_in_distribution():
    """분포에 없는 offset이면 None을 반환한다."""
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) + 0.020))  # offset = +2.0% (분포 밖)

    pos = calc_my_position(my_bid, base_price, llr, _make_distribution())

    assert pos is None


def test_calc_my_position_empty_distribution():
    """빈 분포는 None을 반환한다."""
    pos = calc_my_position(87_000_000, 100_000_000, Decimal("0.87745"), [])
    assert pos is None


def test_calc_my_position_zero_count_bin_skipped():
    """count가 0인 bin은 historical_win_rate 계산에서 제외된다."""
    distribution = [
        {"offset_pct": -0.6, "count": 0, "win_count": 0},
    ]
    base_price = 100_000_000
    llr = Decimal("0.87745")
    my_bid = int(base_price * (float(llr) - 0.006))

    pos = calc_my_position(my_bid, base_price, llr, distribution)

    assert pos is None
