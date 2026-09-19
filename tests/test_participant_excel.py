"""
tests/test_participant_excel.py
info21c 참여자 Excel 파서 검증.

참여자 Excel 한 장에는 세 덩어리가 있다:
  1. 헤더 블록 — 공고번호, 추정가격, 낙찰하한율, 예정가격(+A값), 낙찰하한가 …
  2. 복수예가 15개 + 추첨 선택번호 (①④⑧⑩)
  3. 참여업체 행 — 순위, 등록번호, 업체명, 대표자, 투찰금액, 투찰율

기존 적재는 3번에서 순위·금액·투찰율만 썼다. 나머지는 파일에 이미 있는데
버려지고 있었으므로 (T-035) 한 번의 파싱으로 전부 꺼낸다.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.etl.participant_excel import parse_participant_workbook

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def multi():
    """복수예가 15개 + A값 + 선택번호가 모두 있는 조경 공고."""
    return parse_participant_workbook(FIXTURES / "participants_multi.xlsx")


@pytest.fixture(scope="module")
def fixed():
    """고정예정가격(예가 1개), 낙찰하한율·낙찰하한가 공란인 대학 공고."""
    return parse_participant_workbook(FIXTURES / "participants_sample.xlsx")


# ── 헤더 블록 ────────────────────────────────────────────────────────────────

def test_header_project_id(multi):
    assert multi.project_id == "R25BK00812461-000"


def test_header_amounts(multi):
    assert multi.base_price == 170_984_000
    assert multi.estimated_price == 155_440_000
    assert multi.expected_price == 169_711_075
    assert multi.lower_limit_price == 149_744_394


def test_header_a_value_parsed_from_expected_price_cell(multi):
    # "169,711,075 (A값:6,784,255)" — 예정가격 셀 안에 A값이 같이 온다
    assert multi.a_value == 6_784_255


def test_header_limit_rate_is_decimal_fraction(multi):
    assert multi.declared_limit_rate == Decimal("0.87745")


def test_header_open_datetime(multi):
    assert multi.open_at.isoformat() == "2025-05-01T11:00:00"


def test_header_client_and_region(multi):
    assert multi.client_name == "경기도 남양주시 공원녹지관리사업소"
    assert multi.region == "경기"


def test_header_blank_fields_are_none(fixed):
    assert fixed.declared_limit_rate is None
    assert fixed.lower_limit_price is None
    assert fixed.a_value == 0
    assert fixed.estimated_price == 192_663_637


# ── 복수예가 ─────────────────────────────────────────────────────────────────

def test_preliminary_prices_all_fifteen(multi):
    assert [p.num for p in multi.preliminary_prices] == list(range(1, 16))
    p1 = multi.preliminary_prices[0]
    assert p1.price == 166_894_100
    assert p1.base_pct == Decimal("-2.392")   # 97.608 → 기초 대비 편차 %


def test_preliminary_selected_numbers(multi):
    selected = [p.num for p in multi.preliminary_prices if p.is_selected]
    assert selected == [1, 4, 8, 10]


def test_preliminary_single_price_without_selection(fixed):
    assert len(fixed.preliminary_prices) == 1
    assert fixed.preliminary_prices[0].price == 210_000_000
    assert not fixed.preliminary_prices[0].is_selected


# ── 참여업체 행 ──────────────────────────────────────────────────────────────

def test_rows_carry_company_identity(multi):
    first = multi.rows[0]
    assert first.rank == 1
    assert first.company_id == "4538801481"
    assert first.company_name == "(주)대경조경"
    assert first.ceo_name == "최옥희"
    assert first.bid_amount == 151_259_200
    assert first.bid_rate == Decimal("0.886747")


def test_rows_keep_original_rank_gaps(multi):
    # 3순위가 빠진 파일 — 순위를 다시 매기지 않는다
    assert [r.rank for r in multi.rows] == [1, 2, 4]


def test_rows_company_id_is_string_not_float(fixed):
    # pandas 가 등록번호를 float 로 읽어 '1358801638.0' 이 되는 사고를 막는다
    assert fixed.rows[0].company_id == "1358801638"
