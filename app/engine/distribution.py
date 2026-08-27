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


def _as_bins(data: list[dict] | None) -> list[dict] | None:
    """참여자 원시 행이면 집계하고, 이미 bin 이면 그대로 쓴다.

    조회 경로는 SQL 에서 집계해 bin 을 바로 주고(4.5M 행을 파이썬으로 올리면
    RAM 1GB 서버가 스래싱으로 멈춘다 — 실측), 백테스트·테스트는 원시 행을 넘긴다.
    둘 다 받도록 여기서 한 번만 판별한다.
    """
    if not data:
        return data
    return data if "offset_pct" in data[0] else build_offset_distribution(data)


def build_scoped_distribution(
    rows: list[dict],
    global_rows: list[dict] | None = None,
) -> list[dict]:
    """
    필터된 표본으로 막대 높이를, 글로벌 표본으로 낙찰 빈도를 계산한다.

    두 지표는 요구 표본량이 한 자릿수 배 이상 차이난다.
      - count(참여 분포 모양): 발주처 1곳도 공고 수십 건이면 형태가 잡힌다
      - win_count(낙찰 빈도) : 공고 1건당 낙찰자는 1명뿐이라, 공고 40건이면
                               bin 100여 개에 낙찰자 40명이 흩어져 순수 노이즈가 된다

    그래서 count만 좁히고 낙찰 빈도는 항상 전체 표본에서 가져온다.

    Args:
        rows: 선택된 fallback 레벨의 참여자 행 **또는** 이미 집계된 bin 목록
        global_rows: 전체 참여자 행/bin. None이면 rows를 그대로 쓴다 (= 글로벌 레벨)

    Returns:
        offset_pct 오름차순 bin 목록.
        각 bin: {offset_pct, count(필터), win_count(글로벌), historical_win_rate(글로벌)}
    """
    scoped = _as_bins(rows) or []
    source = scoped if global_rows is None else (_as_bins(global_rows) or [])

    win_by_offset = {b["offset_pct"]: b for b in source}

    merged: list[dict] = []
    for b in scoped:
        g = win_by_offset.get(b["offset_pct"])
        # 글로벌 표본에 해당 구간이 아예 없으면 낙찰 빈도는 0%가 아니라 "값 없음"이다.
        win_count = g["win_count"] if g else 0
        win_rate = round(g["win_count"] / g["count"] * 100, 2) if g and g["count"] > 0 else None
        merged.append({
            "offset_pct": b["offset_pct"],
            "count": b["count"],
            "win_count": win_count,
            "historical_win_rate": win_rate,
        })
    return merged


def calc_my_position(
    my_bid_price: int,
    base_price: int,
    lower_limit_rate: Decimal,
    distribution: list[dict],
    a_value: int = 0,
) -> dict | None:
    """
    내 투찰가의 분포상 위치를 계산한다.

    분포의 x축은 원본 `투찰율(%)` 기준이고, 그 투찰율은 A값이 제거된 조정값이다.

        투찰율 = (투찰금액 − A) / (예정가격 − A)

    따라서 내 위치도 같은 방식으로 조정해야 축이 맞는다.
    A값을 빼지 않으면 A값 크기만큼 오른쪽으로 밀린 위치가 나온다.
    근거: md/design/bid_rate_definitions.md

    사정률≈1.0 근사 사용 (예정가격 ≈ 기초금액):
        my_offset ≈ (my_bid_price − A) / (base_price − A) − lower_limit_rate

    Args:
        my_bid_price: 내 투찰가 (원)
        base_price: 기초금액 (원)
        lower_limit_rate: 법정 낙찰하한율 (Decimal). 실효 하한율이 아니다.
        distribution: build_offset_distribution() 결과
        a_value: A값 (원). 0이면 기존 계산과 동일.

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

    # A값이 예정가격(≈기초금액) 이상이면 이상값 — 무시하고 A값 없이 계산한다.
    a = a_value if 0 < a_value < base_price else 0

    adjusted_rate = (Decimal(my_bid_price) - Decimal(a)) / (Decimal(base_price) - Decimal(a))
    my_offset_pct = round(
        (float(adjusted_rate) - float(lower_limit_rate)) * 100,
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

    # build_scoped_distribution() 이 넣어준 글로벌 기준 값이 있으면 그걸 쓴다.
    # 여기서 win_count/count 로 다시 계산하면 글로벌 낙찰수 ÷ 필터된 참여수가 되어 틀린다.
    if matching_bin.get("historical_win_rate") is not None:
        historical_win_rate = matching_bin["historical_win_rate"]
    else:
        historical_win_rate = matching_bin["win_count"] / matching_bin["count"] * 100

    # offset → 금액 역변환. A값 조정의 역이므로 (예정가격 − A) × rate + A.
    rate = Decimal(str(lower_limit_rate)) + Decimal(str(my_offset_pct)) / Decimal(100)
    estimated_price = int((Decimal(base_price) - Decimal(a)) * rate + Decimal(a))

    return {
        "offset_pct": my_offset_pct,
        "estimated_price": estimated_price,
        "percentile": round(percentile, 2),
        "historical_win_rate": round(historical_win_rate, 2),
        "sample_count": matching_bin["count"],
    }
