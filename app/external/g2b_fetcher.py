"""
app/external/g2b_fetcher.py
나라장터(G2B) 차세대 OpenAPI 연동 레이어 (2025년 신규 API 기준).

사용 API:
  1. getDataSetOpnStdBidPblancInfo  — 입찰공고 정보
  2. getDataSetOpnStdScsbidInfo     — 낙찰결과 정보 (기초금액, 하한율 포함)

⚠ 참여업체수(participants)는 개찰 후에만 공개되므로
  입찰 현황 API 또는 DB 히스토리에서 별도 추정이 필요합니다.
  G2BNoticeData.participants 기본값은 100(추정)이며 Override 가능합니다.
"""

from dataclasses import dataclass, field
from decimal import Decimal

import httpx

from app.db.normalize import (
    normalize_project_type,
    normalize_region,
    normalize_bid_type,
    normalize_price_method,
)


# ──────────────────────────────────────────────────────────────
# 공통 상수
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
NOTICE_ENDPOINT  = f"{BASE_URL}/getDataSetOpnStdBidPblancInfo"
SCSBID_ENDPOINT  = f"{BASE_URL}/getDataSetOpnStdScsbidInfo"

DEFAULT_TIMEOUT = 10.0   # 초
DEFAULT_PARTICIPANTS = 100   # 참여업체수 기본 추정값 (공고 시점 미공개)


def parse_project_type(notice_data: dict) -> str | None:
    """
    공고 데이터에서 공종을 추출·정규화하여 반환한다.
    bidprcPsblIndstrytyNm(투찰가능업종명) 텍스트로 판단.
    반환값: "실내건축" / "조경" / None(대상 아님)
    """
    industry_nm = notice_data.get("bidprcPsblIndstrytyNm", "")
    return normalize_project_type(industry_nm)


# ──────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────

@dataclass
class G2BNoticeData:
    """나라장터 공고 파싱 결과."""
    base_price: int
    client_name: str
    region: str
    project_type: str
    # None = 공고에서 낙찰하한율을 확인할 수 없음 (미개찰 등).
    # 임의 상수로 채우지 않는다 — 호출측에서 override를 요구할 것.
    lower_limit_rate: Decimal | None
    participants: int = DEFAULT_PARTICIPANTS   # 공고 시점 미공개 — 기본값 사용
    bid_notice_no: str = ""
    bid_type: str = "적격심사"       # 입찰방식 (G2B: bidMethdNm)
    client_id: str | None = None    # 발주청 코드 (G2B: dmndInsttCd)
    price_method: str = "기타"      # 예정가격 결정방식 (G2B: presmptPrceDcsnMthdNm)


class G2BFetchError(Exception):
    """나라장터 API 호출/파싱 실패 시 발생."""
    pass


# ──────────────────────────────────────────────────────────────
# 실제 G2B Fetcher
# ──────────────────────────────────────────────────────────────

class G2BFetcher:
    """
    나라장터 차세대 OpenAPI 클라이언트.

    두 API를 순차 호출하여 G2BNoticeData를 구성한다.
      Step 1: 입찰공고 API → client_name, region, project_type
      Step 2: 낙찰결과 API → base_price(bssAmt), lower_limit_rate(sucsfLwstlmtRt)

    Args:
        api_key: 공공데이터포털 서비스키 (URL 인코딩 전 원문)
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def fetch(self, bid_notice_id: str) -> G2BNoticeData:
        """
        공고 번호로 필요한 모든 정보를 조합하여 반환한다.

        Args:
            bid_notice_id: 나라장터 입찰공고번호 (예: "2026031112345")

        Returns:
            G2BNoticeData (base_price=0이면 미개찰 공고 — override 필요)

        Raises:
            G2BFetchError: 입찰공고 API 호출/파싱 실패
        """
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            # Step 1: 입찰공고 정보 (필수 — 실패 시 G2BFetchError)
            notice_data = await self._fetch_notice(client, bid_notice_id)
            # Step 2: 낙찰결과(기초금액 + 하한율) — 미개찰이면 빈 dict
            bsns_div_cd = self._parse_bsns_div_cd(notice_data)
            scsbid_data = await self._fetch_scsbid(client, bid_notice_id, bsns_div_cd)

        raw_region = notice_data.get("prtcptPsblRgnNm") or notice_data.get("insttnNm", "")
        raw_project_type = self._parse_project_type(notice_data)
        raw_bid_type = notice_data.get("bidMethdNm", "")
        raw_price_method = notice_data.get("presmptPrceDcsnMthdNm", "")

        # bssAmt: scsbid 우선, 없으면 notice에서 시도 (일부 API 버전에서 제공)
        raw_base_price = scsbid_data.get("bssAmt") or notice_data.get("bssAmt")

        # 낙찰결과 없음(미개찰) — notice 데이터는 보존, base_price=0으로 반환
        # bidding.py에서 overrides.base_price 없으면 400 에러 처리
        base_price = int(raw_base_price) if raw_base_price else 0

        # 낙찰하한율은 기본값을 두지 않는다.
        # 구간·계약법·개정시점에 따라 달라지는 값이라 상수를 채우면
        # 그럴듯하지만 틀린 투찰가가 조용히 나온다.
        # (2025-07-08 지방계약 / 2026-01-30 국가계약 +2%p 상향으로 87.745%는 이미 옛 값)
        # None이면 호출측에서 override를 요구한다.
        sucsf_lwstlmt_rt = scsbid_data.get("sucsfLwstlmtRt")
        lower_limit_rate = (
            Decimal(str(sucsf_lwstlmt_rt)) / 100 if sucsf_lwstlmt_rt else None
        )

        return G2BNoticeData(
            bid_notice_no=bid_notice_id,
            base_price=base_price,
            client_name=notice_data.get("dmndInsttNm", "알 수 없음"),
            client_id=notice_data.get("dmndInsttCd") or None,
            region=normalize_region(raw_region),
            project_type=raw_project_type or "기타",
            lower_limit_rate=lower_limit_rate,
            participants=DEFAULT_PARTICIPANTS,
            bid_type=normalize_bid_type(raw_bid_type),
            price_method=normalize_price_method(raw_price_method),
        )

    async def _fetch_notice(self, client: httpx.AsyncClient, bid_notice_id: str) -> dict:
        """입찰공고 정보 API 호출."""
        params = {
            "ServiceKey": self.api_key,
            "bidNtceNo": bid_notice_id,
            "numOfRows": "1",
            "pageNo": "1",
            "type": "json",
        }
        try:
            resp = await client.get(NOTICE_ENDPOINT, params=params)
            resp.raise_for_status()
            body = resp.json()
            resp_body = body.get("response", {}).get("body", {})
            items_obj = resp_body.get("items", {})
            if isinstance(items_obj, list):
                items = items_obj
            elif isinstance(items_obj, dict):
                items = items_obj.get("item", [])
            else:
                items = []

            if not items:
                raise G2BFetchError(f"입찰공고 없음: bid_notice_id={bid_notice_id}")
            # items가 단일 dict일 수도 있음
            return items if isinstance(items, dict) else items[0]
        except httpx.HTTPStatusError as e:
            raise G2BFetchError(f"입찰공고 API 오류: {e.response.status_code}") from e
        except Exception as e:
            raise G2BFetchError(f"입찰공고 파싱 실패: {e}") from e

    @staticmethod
    def _parse_bsns_div_cd(notice_data: dict) -> str:
        """
        입찰공고 데이터의 bsnsDivNm(업무구분명)으로 bsnsDivCd를 결정한다.
        공사=3, 용역=5, 기타=3(기본값)
        """
        bsns_div_nm = notice_data.get("bsnsDivNm", "")
        if "용역" in bsns_div_nm:
            return "5"
        return "3"  # 공사(기본값)

    async def _fetch_scsbid(self, client: httpx.AsyncClient, bid_notice_id: str, bsns_div_cd: str = "3") -> dict:
        """낙찰결과 API 호출 (기초금액 + 하한율)."""
        params = {
            "ServiceKey": self.api_key,
            "bidNtceNo": bid_notice_id,
            "bsnsDivCd": bsns_div_cd,   # 필수 파라미터 (누락 시 에러코드 08)
            "numOfRows": "1",
            "pageNo": "1",
            "type": "json",
        }
        try:
            resp = await client.get(SCSBID_ENDPOINT, params=params)
            resp.raise_for_status()
            body = resp.json()
            resp_body = body.get("response", {}).get("body", {})
            items_obj = resp_body.get("items", {})
            if isinstance(items_obj, list):
                items = items_obj
            elif isinstance(items_obj, dict):
                items = items_obj.get("item", [])
            else:
                items = []

            if not items:
                # 낙찰결과 없을 경우(미개찰) → 기본값 반환
                return {}
            return items if isinstance(items, dict) else items[0]
        except httpx.HTTPStatusError as e:
            # 낙찰결과 미개찰이면 404 가능 — 기본값 반환
            if e.response.status_code in (404, 400):
                return {}
            raise G2BFetchError(f"낙찰결과 API 오류: {e.response.status_code}") from e
        except Exception as e:
            raise G2BFetchError(f"낙찰결과 파싱 실패: {e}") from e

    @staticmethod
    def _parse_project_type(notice_data: dict) -> str | None:
        return parse_project_type(notice_data)


# ──────────────────────────────────────────────────────────────
# Mock Fetcher (테스트 / 장애 대응)
# ──────────────────────────────────────────────────────────────

class MockG2BFetcher:
    """
    테스트 / G2B 장애 대응용 Mock.
    실제 API 호출 없이 고정 샘플 데이터를 반환한다.
    """

    # 아래 lower_limit_rate 0.87745는 **고정 픽스처 값**이다.
    # 실제 코드 경로의 기본값이 아니며(그런 기본값은 제거했다),
    # 2026년 현행 하한율도 아니다 (10억 미만 공사 기준 89.745%).
    # 기존 테스트가 이 값에 묶여 있어 그대로 둔다.
    _MOCK_DATA: dict[str, G2BNoticeData] = {
        "TEST-001": G2BNoticeData(
            bid_notice_no="TEST-001",
            base_price=1_000_000_000,
            client_name="서울특별시",
            client_id="6110000",
            region="서울",
            project_type="실내건축",
            lower_limit_rate=Decimal("0.87745"),
            participants=152,
            bid_type="적격심사",
            price_method="복수예비가격",
        ),
        "TEST-002": G2BNoticeData(
            bid_notice_no="TEST-002",
            base_price=500_000_000,
            client_name="경기도교육청",
            client_id="7340000",
            region="경기",
            project_type="실내건축",
            lower_limit_rate=Decimal("0.87745"),
            participants=30,
            bid_type="적격심사",
            price_method="복수예비가격",
        ),
    }

    async def fetch(self, bid_notice_id: str) -> G2BNoticeData:
        """Mock 데이터 반환. 없는 공고 번호면 기본값 반환."""
        return self._MOCK_DATA.get(
            bid_notice_id,
            G2BNoticeData(
                bid_notice_no=bid_notice_id,
                base_price=1_000_000_000,
                client_name="기타기관",
                client_id=None,
                region="기타",
                project_type="실내건축",
                lower_limit_rate=Decimal("0.87745"),
                participants=100,
                bid_type="적격심사",
                price_method="기타",
            ),
        )
