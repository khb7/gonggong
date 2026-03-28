# 데이터 수집 파이프라인 설계

## 1. 현황 & 문제

현재 시스템은 특정 공고번호 1건의 정보를 실시간으로 가져오는 것만 구현되어 있다.
`fallback.py`의 4단계 통계 로직이 실제로 작동하려면 **`bids_history` 테이블에 과거 낙찰 데이터가 쌓여 있어야** 한다.
지금은 DB가 비어있어 항상 `fallback_level: "none"`, `predicted_rate: 1.0` 이 반환된다.

```
현재 흐름:
  POST /bid/calculate
    → G2B API (공고 1건)
    → bids_history 조회 → 데이터 없음 → fallback: none
    → predicted_rate = 1.0 (의미 없는 기본값)

목표 흐름:
  [수집기] 매일 전날 낙찰결과 일괄 수집 → bids_history 적재
    → POST /bid/calculate
    → bids_history 조회 → 통계 계산
    → predicted_rate = 실제 과거 낙찰률 기반 예측값
```

---

## 2. G2B API 스펙 (참고자료 확인 완료)

### 2-1. `getDataSetOpnStdScsbidInfo` — 낙찰정보 (핵심)

```
요청 파라미터:
  ServiceKey  = {API_KEY}          ← 필수
  bsnsDivCd   = 3                  ← 필수! 1=물품, 2=외자, 3=공사, 5=용역
  opengBgnDt  = 202507010000       ← 개찰 시작일시 YYYYMMDDHHMM  ※ 1주일 범위 제한
  opengEndDt  = 202507072359       ← 개찰 종료일시 YYYYMMDDHHMM
  numOfRows   = 100
  pageNo      = 1
  type        = json

응답에서 수집할 필드:
  bidNtceNo        → project_id
  bssAmt           → base_price (기초금액, 원)
  sucsfLwstlmtRt   → lower_limit_rate ⚠ % 단위! (예: 89.745) → /100 해서 저장
  fnlSucsfAmt      → winner_price (최종낙찰금액, 원)
  fnlSucsfRt       → 최종낙찰율 (% 단위, 예정가격 대비)
  opengDate        → bid_date (개찰일자 YYYY-MM-DD)
  opengRsltDivNm   → 개찰결과 (개찰완료/유찰/재입찰) — 필터링용
  dmndInsttNm      → client_name (수요기관명) ✓ 공고 API 추가 조회 불필요
  bsnsDivNm        → 업무구분 (공사/용역/물품)
  sucsfYn          → 낙찰여부 Y/N (낙찰자 필터링)
  opengRank        → 개찰순위 (1 = 낙찰자)

⚠ 없는 필드: participants(참여업체수) → 기본값 100 유지
⚠ region 없음 → 공고 API에서만 제공
```

> 이 API는 **투찰업체별** 레코드를 반환한다. 1개 공고에 N개 레코드.
> `sucsfYn=Y` 또는 `opengRank=1`로 낙찰자 레코드만 필터링.

### 2-2. `getDataSetOpnStdBidPblancInfo` — 입찰공고정보 (region 보완용)

```
요청 파라미터:
  ServiceKey    = {API_KEY}        ← 필수
  bidNtceBgnDt  = 202507010000    ← YYYYMMDDHHMM  ※ 1개월 범위 제한
  bidNtceEndDt  = 202507312359
  numOfRows     = 100
  pageNo        = 1
  type          = json

수집할 필드:
  bidNtceNo       → project_id (매칭키)
  prtcptPsblRgnNm → region (참가가능지역명)  ← scsbid에 없어서 이 API 필요
  bsnsDivNm       → 업무구분명 (project_type 보조)

⚠ bssAmt(기초금액) 없음 — scsbid API에서만 제공
```

### 2-3. `getDataSetOpnStdCntrctInfo` — 계약정보 (참고)

```
요청 파라미터:
  cntrctCnclsBgnDate / cntrctCnclsEndDate  ← YYYYMMDD, 1개월 제한
  insttDivCd = 1 또는 2  (1=계약기관, 2=수요기관)
  insttCd = 기관코드  (특정 기관만 수집 시 사용)

→ 현재 시스템에서는 사용 안 함 (bssAmt 없음)
```

### 2-4. 핵심 계산식

```python
# API 응답값                          →  DB 저장값
sucsfLwstlmtRt = 89.745 (%)          →  lower_limit_rate = 0.89745  (/ 100)
fnlSucsfAmt    = 122_845_000 (원)    →  winner_price = 122_845_000
bssAmt         = 136_630_000 (원)    →  base_price = 136_630_000
                                     →  adjustment_rate = 122845000 / 136630000 = 0.899111
```

### 2-5. 에러 코드 (참고)

| Code | 의미 | 조치 |
|------|------|------|
| `00` | 정상 | - |
| `03` | No Data | 해당 기간 데이터 없음, 스킵 |
| `06` | 날짜 Format 오류 | YYYYMMDDHHMM 형식 확인 |
| `07` | 입력범위 초과 | 날짜 범위 확인 (scsbid: 1주일, 입찰공고: 1개월) |
| `08` / `11` | 필수값 누락 | `bsnsDivCd` 포함 여부 확인 |
| `22` | 일일 호출 초과 | 트래픽 증가 신청 필요 |
| `30` | 서비스키 오류 | URL 인코딩 여부 확인 |

---

## 3. 수집 파이프라인 설계

### 3-1. 전체 흐름

```
G2BCollector.run(start_date, end_date)
  ↓
  [1] 낙찰정보 목록 페이징 조회 (1주일 단위로 분할, bsnsDivCd별 반복)
      getDataSetOpnStdScsbidInfo
      (opengBgnDt/opengEndDt, bsnsDivCd=3 공사 / bsnsDivCd=5 용역)
      → sucsfYn=Y 레코드만 필터링 (낙찰자)
      → bidNtceNo, bssAmt, sucsfLwstlmtRt(/100), fnlSucsfAmt, opengDate, dmndInsttNm 추출
      → adjustment_rate = fnlSucsfAmt / bssAmt
  ↓
  [2] bidNtceNo로 공고 정보 조회 (캐시 활용, region 보완)
      getDataSetOpnStdBidPblancInfo (bidNtceNo 단건)
      → prtcptPsblRgnNm 추출 → region
      → 0.1초 지연 (30 tps 제한)
  ↓
  [3] DB UPSERT
      INSERT INTO bids_history ... ON CONFLICT (project_id) DO NOTHING
      (이미 수집된 공고번호 스킵)
  ↓
  [4] (선택) client_statistics 갱신
```

### 3-2. bsnsDivCd 선택 전략

시스템이 **실내건축/조경** 공종을 대상으로 하므로:

| bsnsDivCd | 업무구분 | 포함 여부 |
|-----------|---------|---------|
| 3 | 공사 | ✅ 실내건축, 조경 포함 |
| 5 | 용역 | ✅ 설계·감리 등 포함 가능 |
| 1 | 물품 | ❌ 불필요 |

→ **bsnsDivCd=3(공사)** 부터 시작, 필요 시 5(용역) 추가.

### 3-3. API 호출 비용

공사 기준 1주일 낙찰완료 건수 약 1,000~3,000건 가정:

| 단계 | 호출 수 / 주 | 비고 |
|------|------------|------|
| 낙찰정보 목록 | 10~30회 | 100건씩 페이징 |
| 공고 정보 (region) | 최대 3,000회 | 캐시로 중복 제거 |
| **합계** | ~3,000회/주 | |

**Rate Limit**: 30 tps → 요청 간 **0.1초** 지연 권장
**날짜 범위 제한**:
- 낙찰정보(`scsbid`): **1주일**
- 입찰공고: **1개월**
- 백필 시 1주일 단위로 분할 반복

---

## 4. 새로 만들 파일 구조

```
app/
├── external/
│   ├── g2b_fetcher.py          ← 기존 (단건 조회)
│   └── g2b_collector.py        ← 신규 (날짜 범위 일괄 수집)
├── db/
│   ├── crud.py                 ← 기존 (읽기 전용)
│   └── crud_write.py           ← 신규 (bids_history 쓰기)
└── jobs/
    ├── __init__.py
    ├── collect.py              ← 신규 (수집 실행 진입점)
    └── refresh_stats.py        ← 신규 (client_statistics 갱신)

scripts/
    └── backfill.py             ← 신규 (초기 과거 데이터 수집 스크립트)
```

---

## 5. 각 파일 구현 가이드

### 5-1. `app/external/g2b_collector.py`

```python
"""
날짜 범위로 낙찰결과를 일괄 수집하는 컬렉터.
기존 G2BFetcher와 독립적으로 동작.
"""

@dataclass
class BidRecord:
    """수집된 낙찰 레코드 1건."""
    project_id: str
    base_price: int
    winner_price: int
    lower_limit_rate: Decimal
    adjustment_rate: Decimal      # = winner_price / base_price
    participants: int
    bid_date: date
    client_name: str
    region: str
    project_type: str


class G2BCollector:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._notice_cache: dict[str, dict] = {}   # bidNtceNo → notice 정보 캐시

    async def collect_range(
        self,
        start_date: date,
        end_date: date,
    ) -> list[BidRecord]:
        """
        날짜 범위의 낙찰결과를 모두 수집하여 반환.
        """
        records = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            # 1. 낙찰결과 목록 (페이징)
            raw_list = await self._fetch_scsbid_list(client, start_date, end_date)

            # 2. 각 레코드에 공고 정보 결합
            for raw in raw_list:
                try:
                    record = await self._build_record(client, raw)
                    records.append(record)
                except Exception as e:
                    logger.warning(f"레코드 처리 실패 {raw.get('bidNtceNo')}: {e}")
                    continue

        return records

    async def _fetch_scsbid_list(
        self,
        client: httpx.AsyncClient,
        start_date: date,
        end_date: date,
        bsns_div_cd: str = "3",   # 3=공사, 5=용역
    ) -> list[dict]:
        """낙찰정보 목록 전체 페이징 조회 (1주일 단위로 호출해야 함).

        bsnsDivCd 필수 파라미터.
        날짜 범위 1주일 제한 → 호출 측에서 주 단위 분할 처리.
        sucsfYn=Y(낙찰자) 레코드만 반환하도록 필터링.
        """
        all_items = []
        page = 1
        while True:
            params = {
                "ServiceKey": self.api_key,
                "bsnsDivCd": bsns_div_cd,           # 필수
                "opengBgnDt": start_date.strftime("%Y%m%d") + "0000",  # YYYYMMDDHHMM
                "opengEndDt": end_date.strftime("%Y%m%d") + "2359",
                "pageNo": str(page),
                "numOfRows": "100",
                "type": "json",
            }
            resp = await client.get(SCSBID_ENDPOINT, params=params)
            resp.raise_for_status()
            body = resp.json()

            result_code = body.get("response", {}).get("header", {}).get("resultCode")
            if result_code == "03":   # No Data
                break

            items = body["response"]["body"]["items"].get("item", [])
            if not items:
                break
            if isinstance(items, dict):
                items = [items]

            # 낙찰자(sucsfYn=Y) + 개찰완료만 필터링
            winners = [
                item for item in items
                if item.get("sucsfYn") == "Y"
                and item.get("opengRsltDivNm") == "개찰완료"
            ]
            all_items.extend(winners)

            total = int(body["response"]["body"]["totalCount"])
            if page * 100 >= total:
                break
            page += 1

        return all_items

    async def _build_record(
        self,
        client: httpx.AsyncClient,
        raw: dict,
    ) -> BidRecord:
        """낙찰정보 1건 + 공고 정보(region) 결합."""
        bid_ntce_no = raw["bidNtceNo"]
        base_price = int(raw["bssAmt"])
        winner_price = int(raw.get("fnlSucsfAmt") or raw["bssAmt"])  # fnlSucsfAmt = 최종낙찰금액

        # lower_limit_rate: API는 % 단위 (예: 89.745) → /100 변환
        raw_rate = Decimal(str(raw.get("sucsfLwstlmtRt") or "87.745"))
        lower_limit_rate = raw_rate / 100

        # client_name은 scsbid 응답에 dmndInsttNm으로 포함 → 공고 API 불필요
        client_name = raw.get("dmndInsttNm", "알 수 없음")

        # region은 공고 API에서만 제공 → 캐시 조회
        notice = await self._fetch_notice_cached(client, bid_ntce_no)

        return BidRecord(
            project_id=bid_ntce_no,
            base_price=base_price,
            winner_price=winner_price,
            lower_limit_rate=lower_limit_rate,
            adjustment_rate=Decimal(winner_price) / Decimal(base_price),
            participants=DEFAULT_PARTICIPANTS,   # API에 참여업체수 없음 → 기본값
            bid_date=datetime.strptime(raw["opengDate"], "%Y-%m-%d").date(),
            client_name=client_name,
            region=notice.get("prtcptPsblRgnNm", "기타"),
            project_type=G2BFetcher._parse_project_type(notice),
        )

    async def _fetch_notice_cached(
        self,
        client: httpx.AsyncClient,
        bid_ntce_no: str,
    ) -> dict:
        """공고 정보 캐시 조회 (없으면 API 호출)."""
        if bid_ntce_no not in self._notice_cache:
            await asyncio.sleep(0.1)   # Rate limiting
            params = {
                "ServiceKey": self.api_key,
                "bidNtceNo": bid_ntce_no,
                "numOfRows": "1",
                "pageNo": "1",
                "type": "json",
            }
            resp = await client.get(NOTICE_ENDPOINT, params=params)
            body = resp.json()
            items = body["response"]["body"]["items"].get("item", {})
            self._notice_cache[bid_ntce_no] = (
                items if isinstance(items, dict) else (items[0] if items else {})
            )
        return self._notice_cache[bid_ntce_no]
```

---

### 5-2. `app/db/crud_write.py`

```python
"""
bids_history 쓰기 전용 CRUD.
"""

async def upsert_bids_history(
    db: AsyncSession,
    records: list[BidRecord],
) -> tuple[int, int]:
    """
    레코드 목록을 bids_history에 삽입.
    중복(project_id)은 스킵.

    Returns:
        (inserted_count, skipped_count)
    """
    inserted = 0
    skipped = 0

    for r in records:
        # project_id 중복 체크
        exists = await db.scalar(
            select(BidsHistory.id).where(BidsHistory.project_id == r.project_id)
        )
        if exists:
            skipped += 1
            continue

        db.add(BidsHistory(
            project_id=r.project_id,
            client_name=r.client_name,
            region=r.region,
            project_type=r.project_type,
            base_price=r.base_price,
            lower_limit_rate=r.lower_limit_rate,
            adjustment_rate=r.adjustment_rate,
            winner_price=r.winner_price,
            participants=r.participants,
            bid_date=r.bid_date,
        ))
        inserted += 1

    await db.commit()
    return inserted, skipped
```

> **대안 (성능 우선)**: PostgreSQL `INSERT ... ON CONFLICT (project_id) DO NOTHING`을 사용하면
> 레코드 1건당 별도 SELECT 없이 단일 쿼리로 처리 가능. 수십만 건 백필 시 권장.

---

### 5-3. `app/jobs/collect.py`

```python
"""
일별 수집 잡 — APScheduler 또는 직접 호출용.
"""

async def run_daily_collect():
    """전날 하루치 낙찰결과 수집."""
    yesterday = date.today() - timedelta(days=1)
    await collect_range(yesterday, yesterday)


async def collect_range(start_date: date, end_date: date):
    """날짜 범위 수집 (백필에서도 호출)."""
    collector = G2BCollector(api_key=settings.G2B_API_KEY)
    records = await collector.collect_range(start_date, end_date)

    async with AsyncSessionLocal() as db:
        inserted, skipped = await upsert_bids_history(db, records)

    logger.info(
        f"수집 완료 {start_date}~{end_date}: "
        f"총 {len(records)}건, 신규 {inserted}건, 스킵 {skipped}건"
    )
    return inserted
```

---

### 5-4. `scripts/backfill.py`

```python
"""
초기 과거 데이터 백필 스크립트.
python scripts/backfill.py --start 20250101 --end 20260101

⚠ 주의: 1년치 약 50,000~150,000건, API 호출 수만~수십만 회 예상.
        --delay 옵션으로 요청 간격 조절 (기본 0.1초).
"""

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYYMMDD")
    parser.add_argument("--end",   required=True, help="YYYYMMDD")
    parser.add_argument("--chunk-days", type=int, default=7, help="한 번에 처리할 일수")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y%m%d").date()
    end   = datetime.strptime(args.end,   "%Y%m%d").date()

    current = start
    while current < end:
        chunk_end = min(current + timedelta(days=args.chunk_days - 1), end)
        print(f"수집 중: {current} ~ {chunk_end}")
        inserted = await collect_range(current, chunk_end)
        print(f"  → {inserted}건 신규 적재")
        current = chunk_end + timedelta(days=1)
```

---

## 6. 스케줄링 방법

### 방법 A: APScheduler (FastAPI 앱 내부에 통합)

```python
# app/main.py 에 추가

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.jobs.collect import run_daily_collect

scheduler = AsyncIOScheduler()

@app.on_event("startup")
async def start_scheduler():
    scheduler.add_job(run_daily_collect, "cron", hour=2, minute=0)  # 매일 새벽 2시
    scheduler.start()

@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()
```

`requirements.txt`에 추가: `apscheduler`

### 방법 B: 독립 Python 스크립트 + Windows 작업 스케줄러 (권장)

API 서버와 분리하여 안정성 확보.

```
Windows 작업 스케줄러 설정:
  - 프로그램: python
  - 인수: C:\Users\Lenovo\gonggong\scripts\daily_collect.py
  - 트리거: 매일 02:00
  - 실행 위치: C:\Users\Lenovo\gonggong
```

`scripts/daily_collect.py`:
```python
import asyncio
from app.jobs.collect import run_daily_collect

if __name__ == "__main__":
    asyncio.run(run_daily_collect())
```

### 방법 C: GitHub Actions (배포 환경용)

```yaml
# .github/workflows/daily-collect.yml
on:
  schedule:
    - cron: '0 17 * * *'   # UTC 17:00 = KST 02:00
jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/daily_collect.py
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          G2B_API_KEY:  ${{ secrets.G2B_API_KEY }}
```

---

## 7. client_statistics 캐시 갱신 (선택)

`bids_history`에 데이터가 쌓이면 fallback은 자동으로 동작한다.
단, 조회가 많은 발주처라면 `client_statistics` 테이블에 미리 통계를 계산해두면 응답속도가 빨라진다.

```python
# app/jobs/refresh_stats.py

async def refresh_client_statistics():
    """
    bids_history에서 발주처별 통계를 재계산하여 client_statistics에 저장.
    일별 수집 완료 후 호출.
    """
    async with AsyncSessionLocal() as db:
        # 1. 발주처 + 공종 + 버킷 조합 목록 조회
        # 2. 각 조합에 대해 trimmed_median(), mad() 계산
        # 3. client_statistics UPSERT
        ...
```

현재 `fallback.py`는 `bids_history`를 직접 읽으므로 **이 단계는 필수가 아니다**.
데이터가 1만 건 이상 쌓이고 응답 지연이 느껴질 때 추가하면 된다.

---

## 8. Info21c 데이터 임포트 (G2B API 대안)

### 개요

**Info21c(인포21c)**는 나라장터 입찰 데이터를 분석·조회할 수 있는 상용 시스템으로,
과거 개찰/낙찰 결과·사정률 등을 필터링·다운로드할 수 있다.
G2B API 백필(과거 데이터 일괄 수집)의 대안이자 보완 수단이다.

**접속**: ID `nw8856` / PW `nw8856` (동시 접속 불가, 오전 중 사용 주의)

### 지원 내보내기 형식

- 일반텍스트 기반 Excel / CSV
- 포맷된 Excel
- HTML / 일반텍스트
- 세부 옵션: 구분자 지정, 리포트 제목 포함 여부, 추가 열 제거 등

### 임포트 파이프라인 설계

```
[Info21c에서 수동 내보내기]
  → CSV/Excel 파일 (과거 낙찰 결과, 사정률 등)
  ↓
scripts/import_info21c.py
  → CSV 파싱 → BidRecord 변환
  → G2B API 호출 없이 bids_history UPSERT
  ↓
DB에 대량 과거 데이터 적재 (G2B 백필보다 빠름)
```

### 구현 포인트

```python
# scripts/import_info21c.py (신규)
"""
Info21c에서 내보낸 CSV/Excel을 bids_history에 임포트.
python scripts/import_info21c.py --file data/info21c_export.csv

⚠ 필드 매핑은 Info21c 컬럼명 확인 후 조정 필요.
⚠ sucsfLwstlmtRt가 % 단위이면 /100 변환.
⚠ adjustment_rate = winner_price / base_price 계산 필요.
"""
```

G2B API 백필 전에 Info21c 데이터를 먼저 임포트하면:
- API 호출 부담 최소화
- 더 빠르게 `fallback_level: "none"` → `"client"` 전환 가능

---

## 9. 구현 순서 (권장)

```
0단계: Info21c에서 과거 데이터 CSV 내보내기 → scripts/import_info21c.py 로 초기 적재
        → G2B API 없이 빠르게 bids_history 채우기

1단계: crud_write.py 구현 + 단위 테스트
        → bids_history 삽입/중복 처리 확인

2단계: g2b_collector.py 구현
        → MockCollector로 먼저 테스트 (실제 API 없이)
        → G2B_API_KEY 있을 때 실제 소량(1일치) 테스트

3단계: scripts/backfill.py 로 과거 데이터 적재 (Info21c로 부족한 기간 보완)
        → 최소 3개월치 이상 수집해야 fallback이 의미있어짐
        → 수집 후 fallback_level이 "none"에서 "client"/"region"으로 바뀌는지 확인

4단계: 스케줄러 연결 (방법 A or B)
        → 일별 자동 수집 테스트

5단계: (선택) refresh_stats.py 추가
```

---

## 10. 주의사항

| 항목 | 내용 |
|------|------|
| API Key | 공공데이터포털 서비스키, URL-decode 전 원문 사용. 오류코드 `30` 발생 시 URL 인코딩 여부 확인 |
| Rate Limit | **30 tps** 제한. 요청 사이 0.1초 지연 필수 |
| bsnsDivCd 필수 | scsbid API 호출 시 반드시 포함. 누락 시 오류코드 `08` 반환 |
| 날짜 범위 제한 | scsbid: **1주일**, 입찰공고: **1개월**. 초과 시 오류코드 `07` 반환 |
| 날짜 형식 | scsbid: `YYYYMMDDHHMM` (12자리), 입찰공고: 동일. DB 저장은 Python `date` |
| sucsfLwstlmtRt 단위 | API는 **퍼센트(%)** (예: `89.745`) → `/100` 변환 후 저장. (코드 수정 완료) |
| 필드명 | winner_price: `fnlSucsfAmt` (최종낙찰금액). `sucsfBidAmt` 필드는 존재하지 않음 |
| 낙찰자 필터링 | `sucsfYn=Y` AND `opengRsltDivNm=개찰완료` 로 필터. 유찰/재입찰 스킵 |
| participants | 이 API에 참여업체수 없음 → 기본값 100 유지 |
| 공고번호 형식 | 2025년부터 13자리 (`R25BK00933743`). 이전 데이터는 11자리 형식 혼재 가능 |
| No Data | 오류코드 `03` = 데이터 없음 → 정상 처리, 다음 기간으로 진행 |
| 트랜잭션 | 주별 전체를 하나의 트랜잭션으로 묶으면 중간 실패 시 롤백 가능 |
| 일일 호출 한도 초과 | 오류코드 `22` → 공공데이터포털에서 트래픽 증가 신청 필요 |
