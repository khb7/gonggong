"""
과거 실제 사정률 히스토그램 (app/engine/preprice_histogram.py).

투찰가 계산 페이지에서 사용자가 사정률 c 를 직접 넣을 때, 그 c 가 과거
공고에서 어떤 결과였을지 보여주는 재료다. 예측이 아니라 실측 분포 위에
c 를 긋는 것이라, 여기서 만드는 건 bin 별 개수뿐이다.
"""

from decimal import Decimal

from app.engine.contract_law import LOCAL, NATIONAL, UNKNOWN, AGENCY
from app.engine.preprice_histogram import (
    BIN_START,
    BIN_WIDTH,
    N_BINS,
    build_preprice_histogram,
)


def _rows(*pairs):
    return [(name, Decimal(str(rate))) for name, rate in pairs]


def test_bins_cover_the_legal_generation_range():
    """복수예가 생성범위는 최대 ±3% 다. bin 이 97~103% 를 빈틈없이 덮어야 한다."""
    assert BIN_START == Decimal("0.970")
    assert BIN_START + BIN_WIDTH * N_BINS == Decimal("1.030")


def test_counts_rates_into_bins():
    rows = _rows(("서울특별시", 0.9993), ("서울특별시", 0.99934), ("서울특별시", 1.0015))
    h = build_preprice_histogram(rows, LOCAL)
    assert h.law == LOCAL
    assert h.n == 3
    assert len(h.counts) == N_BINS
    assert sum(h.counts) == 3
    # 0.9993, 0.99934 는 같은 bin(0.9990~0.9995), 1.0015 는 1.0015~1.0020
    i = int((Decimal("0.9993") - BIN_START) / BIN_WIDTH)
    j = int((Decimal("1.0015") - BIN_START) / BIN_WIDTH)
    assert h.counts[i] == 2
    assert h.counts[j] == 1


def test_filters_rows_to_the_same_contract_law():
    """국가계약 발주처 공고에는 국가계약 공고의 사정률만 쓴다 — 산포가 다르다."""
    rows = _rows(("국군재정관리단", 1.001), ("서울특별시", 0.998), ("경기도 연천군", 0.997))
    assert build_preprice_histogram(rows, NATIONAL).n == 1
    assert build_preprice_histogram(rows, LOCAL).n == 2


def test_unknown_law_uses_every_row():
    """발주처를 모르면 전체 혼합 분포다 — 좁게 잡으면 확신을 과장한다."""
    rows = _rows(("국군재정관리단", 1.001), ("서울특별시", 0.998), ("???", 1.0))
    assert build_preprice_histogram(rows, UNKNOWN).n == 3


def test_agency_uses_agency_rows_only():
    rows = _rows(("조달청 인천지방조달청", 1.001), ("서울특별시", 0.998))
    assert build_preprice_histogram(rows, AGENCY).n == 1


def test_drops_rates_outside_range_and_none():
    """97~103% 밖의 값은 규정상 나올 수 없는 값이라 데이터 오류다. 개수에 넣지 않는다."""
    rows = [("서울특별시", Decimal("0.5")), ("서울특별시", None), ("서울특별시", Decimal("1.0"))]
    h = build_preprice_histogram(rows, LOCAL)
    assert h.n == 1
    assert sum(h.counts) == 1


def test_upper_edge_value_lands_in_last_bin():
    h = build_preprice_histogram(_rows(("서울특별시", 1.030)), LOCAL)
    assert h.counts[-1] == 1
