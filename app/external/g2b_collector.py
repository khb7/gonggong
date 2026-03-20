"""
app/external/g2b_collector.py
날짜 범위로 낙찰결과를 일괄 수집하는 컬렉터.
기존 G2BFetcher(단건 조회)와 독립적으로 동작.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Optional

import httpx

from app.external.g2b_fetcher import (
    NOTICE_ENDPOINT,
    SCSBID_ENDPOINT,
    DEFAULT_PARTICIPANTS,
    parse_project_type,
)

logger = logging.getLogger(__name__)

BSNS_DIV_CODES = ["3"]   # 건축공사업·조경식재공사업은 공사(3)만 해당


@dataclass
class BidRecord:
    """수집된 낙찰 레코드 1건."""
    project_id: str
    base_price: int
    winner_price: int
    lower_limit_rate: Decimal
    adjustment_rate: Decimal
    participants: int
    bid_date: date
    client_name: str
    region: str
    project_type: str


class G2BCollector:
    """
    나라장터 낙찰결과 일괄 수집기.

    G2BFetcher(단건 조회)와 달리 날짜 범위 전체를 페이징으로 수집한다.
    collect_range()가 1주일 단위 분할을 내부에서 처리하므로
    호출자는 날짜 범위를 자유롭게 지정할 수 있다.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def collect_range(
        self,
        start_date: date,
        end_date: date,
        skip_dates: set[date] | None = None,
        on_chunk: Optional[Callable[[int, int, date, date, int], None]] = None,
    ) -> list[BidRecord]:
        """
        날짜 범위의 낙찰결과를 모두 수집하여 반환.
        scsbid API 1주일 제한 대응: 내부에서 7일 단위로 분할 처리.
        skip_dates: 이미 수집된 날짜 집합 — 해당 날짜를 모두 포함한 청크는 건너뜀.
        """
        skip_dates = skip_dates or set()
        total_days = (end_date - start_date).days + 1
        total_chunks = (total_days + 6) // 7
        chunk_num = 0

        records = []
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            current = start_date
            while current <= end_date:
                chunk_end = min(current + timedelta(days=6), end_date)
                chunk_num += 1

                # 청크 내 모든 날짜가 이미 수집됐으면 스킵
                chunk_days = {current + timedelta(days=i)
                              for i in range((chunk_end - current).days + 1)}
                if chunk_days.issubset(skip_dates):
                    print(f"[{chunk_num}/{total_chunks}] {current} ~ {chunk_end} 이미 수집됨, 스킵", flush=True)
                    current = chunk_end + timedelta(days=1)
                    continue

                print(f"[{chunk_num}/{total_chunks}] {current} ~ {chunk_end} 수집 중... (누적 {len(records)}건)", flush=True)
                before = len(records)
                chunk_records = await self._collect_chunk(client, current, chunk_end)
                records.extend(chunk_records)
                added = len(records) - before
                print(f"  → {added}건 수집", flush=True)
                if on_chunk:
                    on_chunk(chunk_num, total_chunks, current, chunk_end, len(records))
                current = chunk_end + timedelta(days=1)
        return records

    async def _collect_chunk(
        self,
        client: httpx.AsyncClient,
        start_date: date,
        end_date: date,
    ) -> list[BidRecord]:
        """1주일 이내 구간의 낙찰결과 수집."""
        raw_list, participants_map = await self._fetch_scsbid_all_types(client, start_date, end_date)
        if not raw_list:
            return []

        # region 보완: 공고 정보를 날짜 범위로 배치 조회
        notice_map = await self._prefetch_notices(client, start_date, end_date)

        records = []
        skip_count = 0
        for raw in raw_list:
            try:
                record = self._build_record(raw, notice_map, participants_map)
                records.append(record)
            except Exception:
                skip_count += 1
        if skip_count:
            logger.debug(f"bssAmt/fnlSucsfAmt 없음으로 {skip_count}건 스킵")
        return records

    @staticmethod
    def _get_response_body(body: dict) -> dict | None:
        """G2B API 응답에서 response.body 추출. 에러 응답이면 None 반환."""
        resp = body.get("response") or body.get("nkoneps.com.response.ResponseError", {})
        result_code = resp.get("header", {}).get("resultCode", "")
        if result_code not in ("00", ""):
            logger.warning(f"API 에러 {result_code}: {resp.get('header', {}).get('resultMsg', '')}")
            return None
        return resp.get("body", {})

    async def _fetch_scsbid_all_types(
        self,
        client: httpx.AsyncClient,
        start_date: date,
        end_date: date,
    ) -> tuple[list[dict], dict[str, int]]:
        """공사(3) + 용역(5) 낙찰결과 통합 수집. (낙찰자 목록, 공고별 참여업체수) 반환."""
        results = await asyncio.gather(*[
            self._fetch_scsbid_list(client, start_date, end_date, bsns_div_cd=code)
            for code in BSNS_DIV_CODES
        ])
        all_winners: list[dict] = []
        all_participants: dict[str, int] = {}
        for winners, pmap in results:
            all_winners.extend(winners)
            for ntce_no, cnt in pmap.items():
                all_participants[ntce_no] = all_participants.get(ntce_no, 0) + cnt
        return all_winners, all_participants

    async def _fetch_scsbid_list(
        self,
        client: httpx.AsyncClient,
        start_date: date,
        end_date: date,
        bsns_div_cd: str = "3",
    ) -> tuple[list[dict], dict[str, int]]:
        """낙찰정보 전체 페이징 조회 (동시 처리).
        - winners: sucsfYn=Y + 개찰완료 레코드
        - participants_map: {bidNtceNo: 해당 공고 전체 투찰 업체 수}
        """
        def _base_params() -> dict:
            return {
                "ServiceKey": self.api_key,
                "bsnsDivCd": bsns_div_cd,
                "opengBgnDt": start_date.strftime("%Y%m%d") + "0000",
                "opengEndDt": end_date.strftime("%Y%m%d") + "2359",
                "numOfRows": "500",
                "type": "json",
            }

        def _parse_items(resp_body: dict) -> list[dict]:
            raw = resp_body.get("items")
            if not raw:
                return []
            if isinstance(raw, list):
                return raw
            if isinstance(raw, dict):
                items = raw.get("item", [])
                return [items] if isinstance(items, dict) else items
            return []

        # 1페이지로 totalCount 확인 (429 시 재시도)
        for attempt in range(5):
            resp = await client.get(SCSBID_ENDPOINT, params={**_base_params(), "pageNo": "1"})
            if resp.status_code == 429:
                wait = 2 ** attempt
                logger.warning(f"429 Too Many Requests (page 1, {bsns_div_cd=}), {wait}초 후 재시도")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError(f"scsbid page 1 ({bsns_div_cd=}): 429 재시도 5회 초과 — 일일 한도 초과 가능성")
        first_body = self._get_response_body(resp.json())
        if not first_body:
            return [], {}

        total = int(first_body.get("totalCount", 0))
        total_pages = (total + 499) // 500
        print(f"    ({bsns_div_cd=}) 총 {total}건 / {total_pages}페이지", flush=True)

        # 모든 페이지를 동시 처리 (semaphore로 최대 3개 동시 — 30 tps 제한 대응)
        semaphore = asyncio.Semaphore(3)

        async def fetch_page(page: int) -> list[dict]:
            async with semaphore:
                for attempt in range(5):
                    r = await client.get(SCSBID_ENDPOINT, params={**_base_params(), "pageNo": str(page)})
                    if r.status_code == 429:
                        wait = 2 ** attempt          # 1, 2, 4, 8, 16초
                        logger.warning(f"429 Too Many Requests (page {page}), {wait}초 후 재시도")
                        await asyncio.sleep(wait)
                        continue
                    r.raise_for_status()
                    rb = self._get_response_body(r.json())
                    return _parse_items(rb) if rb else []
                raise RuntimeError(f"page {page}: 429 재시도 5회 초과")

        all_items: list[dict] = _parse_items(first_body)
        if total_pages > 1:
            pages = await asyncio.gather(*[fetch_page(p) for p in range(2, total_pages + 1)])
            for page_items in pages:
                all_items.extend(page_items)

        # 낙찰자 추출 + 참여업체수 집계
        winners: list[dict] = []
        participants_map: dict[str, int] = {}
        for item in all_items:
            ntce_no = item.get("bidNtceNo")
            if ntce_no:
                participants_map[ntce_no] = participants_map.get(ntce_no, 0) + 1
            if item.get("sucsfYn") == "Y" and item.get("opengRsltDivNm") == "개찰완료":
                winners.append(item)

        return winners, participants_map

    async def _prefetch_notices(
        self,
        client: httpx.AsyncClient,
        start_date: date,
        end_date: date,
    ) -> dict[str, dict]:
        """날짜 범위의 공고 정보를 배치 조회 → {bidNtceNo: notice_dict}.

        건별 호출(최대 수천 회) 대신 날짜 범위로 한 번에 조회하여 API 호출을 최소화.
        """
        notice_map: dict[str, dict] = {}
        page = 1
        while True:
            params = {
                "ServiceKey": self.api_key,
                "bidNtceBgnDt": start_date.strftime("%Y%m%d") + "0000",
                "bidNtceEndDt": end_date.strftime("%Y%m%d") + "2359",
                "numOfRows": "500",
                "pageNo": str(page),
                "type": "json",
            }
            resp = await client.get(NOTICE_ENDPOINT, params=params)
            resp.raise_for_status()
            body = resp.json()

            resp_body = self._get_response_body(body)
            if resp_body is None:
                break

            raw_items = resp_body.get("items")
            if not raw_items:
                break
            if isinstance(raw_items, list):
                items = raw_items
            elif isinstance(raw_items, dict):
                items = raw_items.get("item", [])
                if isinstance(items, dict):
                    items = [items]
            else:
                break

            for item in items:
                notice_map[item["bidNtceNo"]] = item

            total = int(resp_body.get("totalCount", 0))
            if page * 500 >= total:
                break
            page += 1
            await asyncio.sleep(0.034)

        return notice_map

    def _build_record(self, raw: dict, notice_map: dict[str, dict], participants_map: dict[str, int]) -> BidRecord:
        """낙찰정보 1건 + 공고 정보(region) 결합. API 호출 없음."""
        bid_ntce_no = raw["bidNtceNo"]
        bss_amt = raw.get("bssAmt", "")
        if not bss_amt:
            raise ValueError(f"bssAmt 없음: {bid_ntce_no}")
        base_price = int(bss_amt)

        fnl_sucsf_amt = raw.get("fnlSucsfAmt", "")
        if not fnl_sucsf_amt:
            raise ValueError(f"fnlSucsfAmt 없음: {bid_ntce_no}")
        winner_price = int(fnl_sucsf_amt)

        # sucsfLwstlmtRt: API는 % 단위 (예: 89.745) → /100 변환
        raw_rate = Decimal(str(raw.get("sucsfLwstlmtRt") or "87.745"))
        lower_limit_rate = raw_rate / 100

        client_name = raw.get("dmndInsttNm", "알 수 없음")
        notice = notice_map.get(bid_ntce_no, {})
        project_type = parse_project_type(notice)
        if project_type == "기타":
            raise ValueError(f"대상 공종 아님: {bid_ntce_no}")

        return BidRecord(
            project_id=bid_ntce_no,
            base_price=base_price,
            winner_price=winner_price,
            lower_limit_rate=lower_limit_rate,
            adjustment_rate=Decimal(winner_price) / Decimal(base_price),
            participants=participants_map.get(bid_ntce_no, DEFAULT_PARTICIPANTS),
            bid_date=datetime.strptime(raw["opengDate"], "%Y-%m-%d").date(),
            client_name=client_name,
            region=notice.get("prtcptPsblRgnNm", "기타"),
            project_type=project_type,
        )
