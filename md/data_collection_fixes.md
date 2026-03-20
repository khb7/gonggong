# 데이터 수집 파이프라인 설계 수정사항

`data_collection.md` 설계 검토 결과 발견된 문제점과 수정 방향.

---

## 🔴 Critical — 구현 전 반드시 수정

### Fix 1. `project_id` unique 제약 누락

**문제**
`app/db/models.py`의 `BidsHistory.project_id`에 `index=True`만 있고 `unique=True`가 없다.
설계에서 중복 스킵 수단으로 제시한 `INSERT ... ON CONFLICT (project_id) DO NOTHING`은
unique 제약이 없으면 동작하지 않고, Python 루프로 중복 체크해도 동시 실행 시 race condition으로 중복 삽입된다.

**수정**
```python
# app/db/models.py — BidsHistory.project_id
# Before
project_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True, ...)

# After
project_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, ...)
```

DB 마이그레이션도 함께 필요:
```sql
ALTER TABLE bids_history ADD CONSTRAINT bids_history_project_id_key UNIQUE (project_id);
```

이후 `crud_write.py`는 SELECT 루프 대신 단일 쿼리로 구현:
```python
# PostgreSQL INSERT ... ON CONFLICT DO NOTHING
stmt = pg_insert(BidsHistory).values([r.__dict__ for r in records])
stmt = stmt.on_conflict_do_nothing(index_elements=["project_id"])
result = await db.execute(stmt)
await db.commit()
inserted = result.rowcount
skipped = len(records) - inserted
```

---

### Fix 2. `G2BCollector.collect_range()`가 주 단위 분할을 하지 않음

**문제**
scsbid API(`getDataSetOpnStdScsbidInfo`)는 날짜 범위를 1주일로 제한한다.
현재 `collect_range(start_date, end_date)`는 받은 날짜를 그대로 `_fetch_scsbid_list()`에 전달한다.
`backfill.py`가 7일 청크로 분할하지만, `jobs/collect.py`나 다른 호출부에서 8일 이상 범위로 직접 호출하면 API 에러코드 `07`이 발생한다.

**수정**
주 단위 분할 책임을 `G2BCollector.collect_range()` 내부로 이동:

```python
async def collect_range(self, start_date: date, end_date: date) -> list[BidRecord]:
    records = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1주일 단위로 분할 (API 범위 제한 대응)
        current = start_date
        while current <= end_date:
            chunk_end = min(current + timedelta(days=6), end_date)
            raw_list = await self._fetch_scsbid_all_types(client, current, chunk_end)
            for raw in raw_list:
                try:
                    record = await self._build_record(client, raw)
                    records.append(record)
                except Exception as e:
                    logger.warning(f"레코드 처리 실패 {raw.get('bidNtceNo')}: {e}")
            current = chunk_end + timedelta(days=1)
    return records
```

`backfill.py`의 청크 분할은 제거하거나 단순히 범위만 전달하도록 변경:
```python
# backfill.py — 청크 루프 불필요, collect_range가 내부에서 처리
inserted = await collect_range(start, end)
```

---

## 🟠 Significant — 구현 전 반영 권장

### Fix 3. bsnsDivCd=5 (용역) 수집 누락

**문제**
설계 3-2절에서 공사(3) + 용역(5) 둘 다 수집한다고 명시했으나,
`_fetch_scsbid_list()`가 기본값 `bsnsDivCd="3"`으로만 호출되고 용역을 순회하는 루프가 없다.

**수정**
```python
# G2BCollector에 추가
BSNS_DIV_CODES = ["3", "5"]   # 3=공사, 5=용역

async def _fetch_scsbid_all_types(
    self,
    client: httpx.AsyncClient,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """공사(3) + 용역(5) 통합 수집."""
    all_items = []
    for code in BSNS_DIV_CODES:
        items = await self._fetch_scsbid_list(client, start_date, end_date, bsns_div_cd=code)
        all_items.extend(items)
    return all_items
```

`collect_range()`에서 `_fetch_scsbid_list()` 대신 `_fetch_scsbid_all_types()` 호출.

---

### Fix 4. region 보완용 공고 API — 건별 호출 → 배치 조회로 변경

**문제**
현재 설계는 낙찰자 1건마다 공고 API를 1번씩 호출(캐시 없으면).
1주일 낙찰 1,000건 기준:
```
1,000건 × 0.1초 rate limit + HTTP 왕복 = 최소 100초 이상
```
공고 API는 날짜 범위(최대 1개월)로 한 번에 전체 조회가 가능하다.

**수정**
`_build_record()` 전에 공고 목록을 날짜 범위로 미리 bulk fetch하여 dict 구성:

```python
async def _prefetch_notices(
    self,
    client: httpx.AsyncClient,
    start_date: date,
    end_date: date,
) -> dict[str, dict]:
    """날짜 범위의 공고 정보를 일괄 조회 → {bidNtceNo: notice_dict}."""
    notice_map = {}
    page = 1
    while True:
        params = {
            "ServiceKey": self.api_key,
            "bidNtceBgnDt": start_date.strftime("%Y%m%d") + "0000",
            "bidNtceEndDt": end_date.strftime("%Y%m%d") + "2359",
            "numOfRows": "100",
            "pageNo": str(page),
            "type": "json",
        }
        resp = await client.get(NOTICE_ENDPOINT, params=params)
        body = resp.json()

        result_code = body.get("response", {}).get("header", {}).get("resultCode")
        if result_code == "03":
            break

        items = body["response"]["body"]["items"].get("item", [])
        if not items:
            break
        if isinstance(items, dict):
            items = [items]

        for item in items:
            notice_map[item["bidNtceNo"]] = item

        total = int(body["response"]["body"]["totalCount"])
        if page * 100 >= total:
            break
        page += 1
        await asyncio.sleep(0.05)

    return notice_map
```

`collect_range()` 흐름 변경:
```python
# Before: 레코드마다 공고 API 호출
for raw in raw_list:
    record = await self._build_record(client, raw)  # 내부에서 공고 API 호출

# After: 먼저 공고 배치 조회 → dict 전달
notice_map = await self._prefetch_notices(client, current, chunk_end)
for raw in raw_list:
    record = self._build_record_sync(raw, notice_map)  # API 호출 없음
```

API 호출 수: 최대 3,000회 → 10~30회 (100배 감소).

---

### Fix 5. scsbid 목록 페이징에 sleep 없음

**문제**
`_fetch_scsbid_list()`의 while 루프에 페이지 간 지연이 없어 연속 요청이 30 tps 제한에 걸릴 수 있다.

**수정**
```python
# _fetch_scsbid_list() while 루프 내, break 직전
await asyncio.sleep(0.05)   # 페이지 간 지연 (20 rps 유지)
page += 1
```

---

## 🟡 Minor — 운영 전 반영

### Fix 6. notice 캐시 크기 무제한 증가

**문제**
`self._notice_cache: dict[str, dict]`가 백필 실행 중 수만 건까지 쌓인다.
Fix 4(배치 조회)를 적용하면 `_notice_cache` 자체가 불필요해지므로 함께 제거.
Fix 4를 적용하지 않는다면 최소한 크기 제한 필요:
```python
from functools import lru_cache
# 또는 dict에 최대 크기 로직 추가
MAX_CACHE = 5_000
if len(self._notice_cache) > MAX_CACHE:
    # 오래된 항목 제거 (간단히 전체 초기화)
    self._notice_cache.clear()
```

---

### Fix 7. `winner_price` fallback이 통계를 오염시킴

**문제**
```python
winner_price = int(raw.get("fnlSucsfAmt") or raw["bssAmt"])
```
`fnlSucsfAmt`가 없을 때 기초금액을 낙찰가로 사용하면 `adjustment_rate = 1.0`이 DB에 저장되어 통계 왜곡.
`sucsfYn=Y AND 개찰완료` 필터를 통과한 레코드엔 항상 `fnlSucsfAmt`가 있어야 하지만, 없다면 스킵하는 게 안전.

**수정**
```python
fnl_sucsf_amt = raw.get("fnlSucsfAmt")
if not fnl_sucsf_amt:
    raise ValueError(f"fnlSucsfAmt 없음 — 낙찰완료 레코드인데 금액 미공개: {raw.get('bidNtceNo')}")
winner_price = int(fnl_sucsf_amt)
```
`collect_range()`의 except 블록이 warning 로그 후 continue하므로 전체 수집은 중단되지 않음.

---

### Fix 8. `G2BFetcher._parse_project_type()` 직접 참조 제거

**문제**
`G2BCollector`가 `G2BFetcher`의 내부 static method를 직접 참조한다.
두 클래스가 불필요하게 커플링되고, `G2BFetcher`를 수정하면 `G2BCollector`가 영향을 받는다.

**수정**
`g2b_fetcher.py`의 `_parse_project_type()`을 모듈 수준 함수로 분리:
```python
# g2b_fetcher.py — 클래스 밖으로 이동
def parse_project_type(notice_data: dict) -> str:
    industry = notice_data.get("indstrytyCd", "")
    mapping = {"10": "실내건축", "20": "조경"}
    return mapping.get(industry[:2], notice_data.get("indstrytyNm", "실내건축"))
```

`G2BCollector`에서는 import해서 사용:
```python
from app.external.g2b_fetcher import parse_project_type
```

---

## 수정 후 구현 순서

```
1단계: models.py — project_id에 unique=True 추가 + DB migration
2단계: crud_write.py — ON CONFLICT DO NOTHING 방식으로 구현
3단계: g2b_fetcher.py — parse_project_type() 모듈 수준으로 이동
4단계: g2b_collector.py 구현
          - collect_range() 내부에서 주 단위 분할
          - _fetch_scsbid_all_types() (공사+용역)
          - _prefetch_notices() (배치 조회)
5단계: jobs/collect.py + scripts/backfill.py 구현
6단계: 스케줄러 연결
```
