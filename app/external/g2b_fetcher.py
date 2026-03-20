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


# ──────────────────────────────────────────────────────────────
# 공통 상수
# ──────────────────────────────────────────────────────────────

BASE_URL = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
NOTICE_ENDPOINT  = f"{BASE_URL}/getDataSetOpnStdBidPblancInfo"
SCSBID_ENDPOINT  = f"{BASE_URL}/getDataSetOpnStdScsbidInfo"

DEFAULT_TIMEOUT = 10.0   # 초
DEFAULT_PARTICIPANTS = 100   # 참여업체수 기본 추정값 (공고 시점 미공개)


def parse_project_type(notice_data: dict) -> str:
    """공고 데이터에서 공종을 추출한다.
    bidprcPsblIndstrytyNm(투찰가능업종명) 텍스트로 판단.
    대상: 건축공사업, 조경식재공사업만 수집. 나머지는 "기타" 반환.
    """
    industry_nm = notice_data.get("bidprcPsblIndstrytyNm", "")
    if "조경식재" in industry_nm:
        return "조경식재공사업"
    if "건축공사업" in industry_nm:
        return "건축공사업"
    return "기타"


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
    lower_limit_rate: Decimal
    participants: int = DEFAULT_PARTICIPANTS   # 공고 시점 미공개 — 기본값 사용
    bid_notice_no: str = ""


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
            G2BNoticeData

        Raises:
            G2BFetchError: API 호출 실패 또는 파싱 실패
        """
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            # Step 1: 입찰공고 정보
            notice_data = await self._fetch_notice(client, bid_notice_id)
            # Step 2: 낙찰결과(기초금액 + 하한율)
            scsbid_data = await self._fetch_scsbid(client, bid_notice_id)

        base_price = scsbid_data.get("bssAmt")
        if not base_price:
            raise G2BFetchError(
                f"기초금액(bssAmt) 없음: bid_notice_id={bid_notice_id}. "
                "미개찰 공고이거나 낙찰결과 미공개 상태입니다. overrides.base_price로 직접 입력하세요."
            )

        return G2BNoticeData(
            bid_notice_no=bid_notice_id,
            base_price=int(base_price),
            client_name=notice_data.get("dmndInsttNm", "알 수 없음"),
            region=notice_data.get("prtcptPsblRgnNm") or notice_data.get("insttnNm", "기타"),
            project_type=self._parse_project_type(notice_data),
            lower_limit_rate=Decimal(str(scsbid_data.get("sucsfLwstlmtRt", "87.745"))) / 100,
            participants=DEFAULT_PARTICIPANTS,
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
            items = (
                body.get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", [])
            )
            if not items:
                raise G2BFetchError(f"입찰공고 없음: bid_notice_id={bid_notice_id}")
            # items가 단일 dict일 수도 있음
            return items if isinstance(items, dict) else items[0]
        except httpx.HTTPStatusError as e:
            raise G2BFetchError(f"입찰공고 API 오류: {e.response.status_code}") from e
        except Exception as e:
            raise G2BFetchError(f"입찰공고 파싱 실패: {e}") from e

    async def _fetch_scsbid(self, client: httpx.AsyncClient, bid_notice_id: str) -> dict:
        """낙찰결과 API 호출 (기초금액 + 하한율)."""
        params = {
            "ServiceKey": self.api_key,
            "bidNtceNo": bid_notice_id,
            "numOfRows": "1",
            "pageNo": "1",
            "type": "json",
        }
        try:
            resp = await client.get(SCSBID_ENDPOINT, params=params)
            resp.raise_for_status()
            body = resp.json()
            items = (
                body.get("response", {})
                    .get("body", {})
                    .get("items", {})
                    .get("item", [])
            )
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
    def _parse_project_type(notice_data: dict) -> str:
        return parse_project_type(notice_data)


# ──────────────────────────────────────────────────────────────
# Mock Fetcher (테스트 / 장애 대응)
# ──────────────────────────────────────────────────────────────

class MockG2BFetcher:
    """
    테스트 / G2B 장애 대응용 Mock.
    실제 API 호출 없이 고정 샘플 데이터를 반환한다.
    """

    _MOCK_DATA: dict[str, G2BNoticeData] = {
        "TEST-001": G2BNoticeData(
            bid_notice_no="TEST-001",
            base_price=1_000_000_000,
            client_name="서울특별시",
            region="서울",
            project_type="실내건축",
            lower_limit_rate=Decimal("0.87745"),
            participants=152,
        ),
        "TEST-002": G2BNoticeData(
            bid_notice_no="TEST-002",
            base_price=500_000_000,
            client_name="경기도교육청",
            region="경기",
            project_type="실내건축",
            lower_limit_rate=Decimal("0.87745"),
            participants=30,
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
                region="기타",
                project_type="실내건축",
                lower_limit_rate=Decimal("0.87745"),
                participants=100,
            ),
        )
