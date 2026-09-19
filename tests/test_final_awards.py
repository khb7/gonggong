"""
tests/test_final_awards.py
info21c 최종낙찰현황(/suc/last/con) 표 행 → 레코드 변환 검증.

표 한 행: 번호 | 공고명/공고번호 | 발주기관 | 개찰일 | 낙찰금액 | 업체명 | 대표자 | 주소
공고번호는 공고명 뒤 대괄호 안에 온다. 실제 계약 업체가 1순위와 다른 비율을
재는 것이 목적이므로 공고번호와 업체 식별이 핵심이다.
"""

from datetime import date

from app.etl.info21c_final_awards import parse_final_award_row


ROW = [
    "1",
    "2026년 국립세종수목원 가든샵 별동증축 건축조성 공사(건축기계) [R26BK01728000-000]",
    "국립세종수목원",
    "26.09.18",
    "218,283,700",
    "주식회사 디큐종합건설",
    "김남규",
    "서울특별시 강남구 봉은사로 129-0 (논현동) 516호",
]


def test_project_id_from_bracket_suffix():
    r = parse_final_award_row(ROW, "/suc/view/con/260914155214064-00-00-01")
    assert r.project_id == "R26BK01728000-000"
    assert r.notice_title == "2026년 국립세종수목원 가든샵 별동증축 건축조성 공사(건축기계)"


def test_award_fields():
    r = parse_final_award_row(ROW, "/suc/view/con/260914155214064-00-00-01")
    assert r.client_name == "국립세종수목원"
    assert r.open_date == date(2026, 9, 18)
    assert r.award_amount == 218_283_700
    assert r.company_name == "주식회사 디큐종합건설"
    assert r.ceo_name == "김남규"
    assert r.address.startswith("서울특별시 강남구")


def test_info21c_bidid_from_link():
    r = parse_final_award_row(ROW, "https://web.info21c.net/suc/view/con/260914155214064-00-00-01")
    assert r.info21c_bidid == "260914155214064-00-00-01"


def test_nested_brackets_in_title_still_find_notice_no():
    row = list(ROW)
    row[1] = "2026년 큰나무가꾸기사업 [(영천시)(재입찰)] [R26BK01723561-000]"
    r = parse_final_award_row(row, None)
    assert r.project_id == "R26BK01723561-000"
    assert r.notice_title == "2026년 큰나무가꾸기사업 [(영천시)(재입찰)]"
    assert r.info21c_bidid is None


def test_row_without_notice_no_is_skipped():
    row = list(ROW)
    row[1] = "공고번호 없는 행"
    assert parse_final_award_row(row, None) is None
