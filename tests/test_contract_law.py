"""
발주처 → 적용 계약법 판별과 사정률 산포 (app/engine/contract_law.py).

복수예비가격 생성범위는 규정으로 정해져 있다 —
국가계약법 ±2% / 지방계약법 ±3%. 따라서 사정률 산포는 추정 대상이 아니다.
"""

from decimal import Decimal

import pytest

from app.engine.contract_law import (
    AGENCY,
    LOCAL,
    NATIONAL,
    UNKNOWN,
    PREPRICE_MAD,
    PREPRICE_SD,
    classify,
    preprice_mad,
    preprice_sd,
)


# ── 판별 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "국군재정관리단",
    "제5군단사령부",
    "제2136부대",
    "조달청",
    "한국토지주택공사",
    "한국수력원자력 한울원자력본부",
    "국가철도공단",
    "중소기업은행",
    "한경국립대학교",
    "국토교통부 서울지방국토관리청 수원국토관리사무소",
])
def test_classify_national(name):
    assert classify(name) == NATIONAL


@pytest.mark.parametrize("name", [
    "경기도 화성시",
    "경기도교육청 경기도용인교육지원청",
    "서울특별시",
    "고양시 일산서구청",
    "남양주도시공사",
    "경기관광공사",
])
def test_classify_local(name):
    assert classify(name) == LOCAL


def test_classify_agency_is_not_national():
    """지방조달청은 지자체 조달을 **대행**한다 — 국가로 분류하면 안 된다.

    이름에 '조달청'이 들어가지만 계약 주체가 아니다. 실측 sd 가
    0.602(충북)~0.793(부산) 로 흩어져 국가(0.549)로도 지방(0.744)으로도
    묶이지 않는다. 이름만으로는 판별 불가라 별도 범주다.
    """
    assert classify("조달청 인천지방조달청") == AGENCY
    assert classify("조달청 대전지방조달청") == AGENCY
    # 본청은 국가다
    assert classify("조달청") == NATIONAL


def test_classify_army_is_not_local():
    """'육군'은 `\\S+군$` 에 걸려 지방으로 오분류되기 쉽다.

    판별 순서(국가 마커 먼저)가 이걸 막는다.
    """
    assert classify("육군 제1군단") == NATIONAL
    assert classify("수도군단") == NATIONAL


@pytest.mark.parametrize("name", ["", None, "None", "   "])
def test_classify_unknown(name):
    assert classify(name) == UNKNOWN


# ── 산포 ──────────────────────────────────────────────────────


def test_national_spread_is_narrower_than_local():
    """±2% 생성범위가 ±3% 보다 좁다 — 규정에서 따라오는 부등식이다."""
    assert PREPRICE_SD[NATIONAL] < PREPRICE_SD[LOCAL]
    assert PREPRICE_MAD[NATIONAL] < PREPRICE_MAD[LOCAL]


def test_spread_matches_regulation_theory():
    """강민석·류문찬(2015) Table 3 의 이론 sd 와 같은 자릿수여야 한다.

    ±2% → 0.513% / ±3% → 0.767%.
    크게 벗어나면 사정률 적재나 발주처 판별이 오염된 것이다.
    """
    assert Decimal("0.004") < PREPRICE_SD[NATIONAL] < Decimal("0.006")
    assert Decimal("0.0065") < PREPRICE_SD[LOCAL] < Decimal("0.0085")


def test_unknown_falls_back_to_global_mix():
    """모르는 발주처는 넓게 잡는다 — 좁게 잡으면 확신을 과장한다."""
    assert PREPRICE_SD[UNKNOWN] >= PREPRICE_SD[NATIONAL]


def test_helpers_route_through_classify():
    assert preprice_sd("경기도 화성시") == PREPRICE_SD[LOCAL]
    assert preprice_sd("국군재정관리단") == PREPRICE_SD[NATIONAL]
    assert preprice_mad("조달청 인천지방조달청") == PREPRICE_MAD[AGENCY]
    assert preprice_sd(None) == PREPRICE_SD[UNKNOWN]
