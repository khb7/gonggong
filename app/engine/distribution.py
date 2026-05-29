"""
app/engine/distribution.py
경쟁자 offset 분포 계산 모듈.

offset = bid_rate - lower_limit_rate
       = (투찰금액/예정가격) - (낙찰하한가/예정가격)

0.1% 간격 히스토그램으로 집계하여 시장 분포와 내 위치를 계산한다.
"""

from decimal import Decimal

# bin 해상도: 0.1% = 0.001
_BIN_PCT_RESOLUTION = 1  # round() 소수점 자릿수 (% 단위 기준)


def _to_offset_pct(bid_rate: Decimal, lower_limit_rate: Decimal) -> float:
    """offset을 % 단위로 변환하고 0.1% 단위로 반올림한다."""
    offset = bid_rate - lower_limit_rate
    return round(float(offset) * 100, _BIN_PCT_RESOLUTION)


def build_offset_distribution(rows: list[dict]) -> list[dict]:
    """
    참여자 행 목록에서 offset 히스토그램을 빌드한다.

    Args:
        rows: DB에서 조회한 참여자 행 목록.
              각 행에 bid_rate(Decimal), lower_limit_rate(Decimal), is_winner(bool) 필요.

    Returns:
        offset_pct 오름차순 정렬된 bin 목록.
        각 bin: {offset_pct: float, count: int, win_count: int}
    """
    bins: dict[float, dict] = {}

    for row in rows:
        key = _to_offset_pct(row["bid_rate"], row["lower_limit_rate"])
        if key not in bins:
            bins[key] = {"offset_pct": key, "count": 0, "win_count": 0}
        bins[key]["count"] += 1
        if row["is_winner"]:
            bins[key]["win_count"] += 1

    return sorted(bins.values(), key=lambda b: b["offset_pct"])


def calc_my_position(
    my_bid_price: int,
    base_price: int,
    lower_limit_rate: Decimal,
    distribution: list[dict],
) -> dict | None:
    """
    내 투찰가의 분포상 위치를 계산한다.

    사정률≈1.0 근사 사용:
        my_offset ≈ (my_bid_price / base_price) - lower_limit_rate

    Args:
        my_bid_price: 내 투찰가 (원)
        base_price: 기초금액 (원)
        lower_limit_rate: 낙찰하한율 (Decimal)
        distribution: build_offset_distribution() 결과

    Returns:
        {
            offset_pct: float,           내 offset (%)
            estimated_price: int,        기초금액 × (하한율 + offset) (원)
            percentile: float,           내 위치보다 낮은 참여자 비율 (%)
            historical_win_rate: float,  해당 bin의 과거 낙찰 빈도 (%)
            sample_count: int,           해당 bin의 참여 건수
        }
        또는 None (분포에 매칭 bin 없거나 count=0인 경우)
    """
    if not distribution:
        return None

    my_offset_pct = round(
        (float(Decimal(str(my_bid_price)) / Decimal(str(base_price))) - float(lower_limit_rate)) * 100,
        _BIN_PCT_RESOLUTION,
    )

    matching_bin = next(
        (b for b in distribution if b["offset_pct"] == my_offset_pct),
        None,
    )
    if matching_bin is None or matching_bin["count"] == 0:
        return None

    total_count = sum(b["count"] for b in distribution)

    percentile = (
        sum(b["count"] for b in distribution if b["offset_pct"] < my_offset_pct)
        / total_count
        * 100
    )

    historical_win_rate = matching_bin["win_count"] / matching_bin["count"] * 100

    estimated_price = int(base_price * (float(lower_limit_rate) + my_offset_pct / 100))

    return {
        "offset_pct": my_offset_pct,
        "estimated_price": estimated_price,
        "percentile": round(percentile, 2),
        "historical_win_rate": round(historical_win_rate, 2),
        "sample_count": matching_bin["count"],
    }
