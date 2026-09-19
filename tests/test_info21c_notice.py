"""
tests/test_info21c_notice.py
info21c 개찰 전 공고 상세 페이지(/bid/view/con/{id}) 텍스트 파서 검증.

페이지 innerText 를 그대로 넣는다. 브라우저에서 긁은 실제 텍스트(2026-09-19,
구리시 갈매수변공원 공고)를 줄여서 픽스처로 쓴다. 이 페이지 하나에
분포 엔진 입력(기초금액·하한율·A값·발주처·지역·업종)이 전부 있고,
예가변동폭(±2/±3)으로 계약법까지 바로 갈린다.
"""

from datetime import datetime
from decimal import Decimal

import pytest

from app.etl.info21c_notice import parse_open_notice_text

SAMPLE = """\
뒤로가기
 입찰가격산정 프리즘2.0 적격심사업체검색 인쇄 서류함
2026년 갈매수변공원 생활환경숲 조성 공사 [(구리시)]관내수의기초A값
기본정보
업종\t조경(식재.시설물)[대],조경식재,조경시설물\t공고번호\tR26BK01737250-001
상세업종\t(4993) 조경식재.시설물공사업[대]
지역\t경기\t발주기관\t
경기도 구리시
발주처심층분석

수요기관\t경기도 구리시\t계약방법\t수의
예가방법\t복수예가:4(추첨예가)/15(총예가)\t담당자 전화번호\t전** (☎ -)
예가변동폭\t-3 ~ +3\t낙찰하한율\t89.745%

A값
\t5,904,323 원\t
순공사원가
\t
기초금액\t
155,087,000 원
입찰가격산정
\t추정가격\t140,988,182 원
일시정보
PQ마감일시\t\t공고게시일\t2026년 09월 18일
실적제출마감\t\t입력일\t2026년 09월 18일
참가등록마감\t2026년 09월 27일 18시 00분\t투찰시작일\t
2026년 09월 21일 12시 00분

협정마감일시\t
\t현장설명일시\t
투찰마감일시\t
2026년 09월 28일 12시 00분
투찰하기
\t개찰일시\t2026년 09월 28일 14시 00분
투찰시작일
(09/21 12:00)
1일 남음\t참가마감
자격및 특기사항
※ [필독] 금액정보(기초금액, 추정가격, A값 등) 발표가 늦거나 변동되는 경우가 있습니다.
"""


@pytest.fixture(scope="module")
def n():
    return parse_open_notice_text(SAMPLE)


def test_project_id(n):
    assert n.project_id == "R26BK01737250-001"


def test_title_without_tag_suffix(n):
    # 제목 뒤에 붙는 '관내수의기초A값' 은 태그 뭉치라 제목에서 뗀다
    assert n.notice_title == "2026년 갈매수변공원 생활환경숲 조성 공사 [(구리시)]"


def test_client_region_license(n):
    assert n.client_name == "경기도 구리시"
    assert n.region == "경기"
    assert n.license_text == "조경(식재.시설물)[대],조경식재,조경시설물"


def test_amounts(n):
    assert n.base_price == 155_087_000
    assert n.estimated_price == 140_988_182
    assert n.a_value == 5_904_323


def test_limit_rate_is_fraction(n):
    assert n.legal_limit_rate == Decimal("0.89745")


def test_preprice_range_pct(n):
    # '-3 ~ +3' → 지방계약(±3%). 국가계약이면 '-2 ~ +2'
    assert n.preprice_range_pct == 3


def test_contract_and_price_method(n):
    assert n.contract_method == "수의"
    assert n.price_method == "복수예비가격"


def test_datetimes(n):
    assert n.bid_close_at == datetime(2026, 9, 28, 12, 0)
    assert n.open_at == datetime(2026, 9, 28, 14, 0)


def test_missing_fields_are_none_not_guessed():
    # 하한율·A값이 아직 발표되지 않은 공고 — 채워 넣지 않는다 (CLAUDE.md: 모르면 None)
    text = SAMPLE.replace("낙찰하한율\t89.745%", "낙찰하한율\t").replace("\t5,904,323 원\t", "\t\t")
    m = parse_open_notice_text(text)
    assert m.legal_limit_rate is None
    assert m.a_value == 0
    assert m.base_price == 155_087_000


def test_no_project_id_raises():
    with pytest.raises(ValueError):
        parse_open_notice_text("기본정보\n업종\t조경\n")
