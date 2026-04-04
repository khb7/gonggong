# 데이터 재수집 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 손상된 bids_history 데이터를 삭제하고, 상세 포맷으로 재수집하여 lower_limit_rate·participants·region·price_method가 올바르게 적재되도록 한다.

**Architecture:** (1) DB에 g2b_code 컬럼 추가 + TRUNCATE → (2) ETL에서 신규 컬럼 처리 추가 → (3) 품질 검증 스크립트 작성 → (4) --debug 테스트 다운로드 → (5) 자동 백필

**Tech Stack:** Python 3.11, SQLAlchemy + asyncpg, Alembic, pandas, asyncio

---

## Task 1: g2b_code 컬럼 추가 — 모델 + 마이그레이션

**Files:**
- Modify: `app/db/models.py`
- Create: `alembic/versions/` (자동 생성)

- [ ] **Step 1: models.py에 g2b_code 컬럼 추가**

`app/db/models.py`의 `BidsHistory` 클래스에서 `created_at` 필드 바로 위에 추가:

```python
g2b_code: Mapped[str | None] = mapped_column(
    String(50), nullable=True, index=True,
    comment="나라장터 공사 분류 코드 (g2b분류)"
)
```

- [ ] **Step 2: 마이그레이션 생성**

```bash
cd c:\Users\Lenovo\gonggong
alembic revision --autogenerate -m "add_g2b_code"
```

생성된 파일(`alembic/versions/xxxx_add_g2b_code.py`)을 열어 upgrade/downgrade 내용 확인:
```python
# upgrade 함수에 아래가 있어야 함
op.add_column('bids_history', sa.Column('g2b_code', sa.String(50), nullable=True))
```

- [ ] **Step 3: 마이그레이션 적용**

```bash
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Running upgrade ... -> xxxx, add_g2b_code
```

- [ ] **Step 4: DB에서 컬럼 확인**

```bash
python -c "
import asyncio, asyncpg
async def check():
    conn = await asyncpg.connect('postgresql://postgres@localhost:5432/gonggong')
    cols = await conn.fetch(\"SELECT column_name FROM information_schema.columns WHERE table_name='bids_history' ORDER BY ordinal_position\")
    print([c['column_name'] for c in cols])
    await conn.close()
asyncio.run(check())
"
```

Expected: 리스트에 `'g2b_code'` 포함

- [ ] **Step 5: 기존 데이터 삭제**

```bash
python -c "
import asyncio, asyncpg
async def truncate():
    conn = await asyncpg.connect('postgresql://postgres@localhost:5432/gonggong')
    await conn.execute('TRUNCATE TABLE bids_history RESTART IDENTITY')
    count = await conn.fetchval('SELECT COUNT(*) FROM bids_history')
    print(f'bids_history 레코드 수: {count}')
    await conn.close()
asyncio.run(truncate())
"
```

Expected: `bids_history 레코드 수: 0`

- [ ] **Step 6: 커밋**

```bash
git add app/db/models.py alembic/versions/
git commit -m "feat: bids_history에 g2b_code 컬럼 추가 + 기존 데이터 TRUNCATE"
```

---

## Task 2: ETL 수정 — 신규 컬럼 처리

**Files:**
- Modify: `scripts/etl_csv.py`
- Test: `tests/test_etl_csv.py`

### 배경

Info21c 상세 포맷에서 새로 추가되는 컬럼 3개를 처리해야 한다.

| Info21c 컬럼 | DB 컬럼 | 처리 방식 |
|---|---|---|
| `예정가격결정방식` | `price_method` | 있으면 매핑, 없으면 `"기타"` |
| `1순위사정율` | `adjustment_rate` 검증용 | 있으면 계산값과 대조 후 직접 사용 |
| `g2b분류` | `g2b_code` | 있으면 그대로 저장 |

- [ ] **Step 1: 테스트 파일 작성**

`tests/test_etl_csv.py` 신규 생성:

```python
"""
scripts/etl_csv.py 신규 컬럼 처리 테스트.
DB 연결 없이 extract_and_transform() 만 검증한다.
"""
import io
import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from pathlib import Path
from scripts.etl_csv import extract_and_transform, normalize_price_method


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def make_csv(rows: list[dict]) -> Path:
    """임시 CSV 파일 생성 후 Path 반환."""
    import tempfile
    df = pd.DataFrame(rows)
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w",
                                     encoding="utf-8-sig")
    df.to_csv(tmp.name, index=False)
    return Path(tmp.name)


BASE_ROW = {
    "입찰공고번호": "TEST-001",
    "개찰순위": "1",
    "면허업종제한목록": "실내건축공사업[0002]",
    "낙찰하한율": "87.745",
    "기초금액": "100000000",
    "예산가격": "100000000",   # adjustment_rate = 1.0
    "투찰금액": "87745000",
    "입찰참여자수": "42",
    "투찰일자": "2025-01-15",
    "낙찰방법": "적격심사",
    "수요기관": "테스트기관",
    "수요기관지역": "경기",
    "수요기관사업자등록번호": "123-45-67890",
}


# ── price_method 정규화 ──────────────────────────────────────────────────────

def test_normalize_price_method_복수예비가격():
    assert normalize_price_method("복수예비가격") == "복수예비가격"

def test_normalize_price_method_고정예정가격():
    assert normalize_price_method("고정예정가격") == "고정예정가격"

def test_normalize_price_method_unknown():
    assert normalize_price_method("기타방식") == "기타"

def test_normalize_price_method_empty():
    assert normalize_price_method("") == "기타"


# ── price_method 컬럼 매핑 ───────────────────────────────────────────────────

def test_price_method_mapped_when_column_exists():
    row = {**BASE_ROW, "예정가격결정방식": "복수예비가격"}
    path = make_csv([row])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["price_method"] == "복수예비가격"


def test_price_method_default_when_column_missing():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["price_method"] == "기타"


# ── 1순위사정율 처리 ─────────────────────────────────────────────────────────

def test_adjustment_rate_from_1순위사정율_when_column_exists():
    """1순위사정율 컬럼이 있으면 직접 사용한다 (퍼센트 → 소수 변환)."""
    row = {**BASE_ROW, "1순위사정율": "99.5"}  # 퍼센트 단위
    path = make_csv([row])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert abs(float(df.iloc[0]["adjustment_rate"]) - 0.995) < 0.0001


def test_adjustment_rate_computed_when_column_missing():
    """1순위사정율 컬럼이 없으면 예산가격/기초금액으로 계산한다."""
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert len(df) == 1
    # 예산가격=기초금액=100000000 → adjustment_rate = 1.0
    assert abs(float(df.iloc[0]["adjustment_rate"]) - 1.0) < 0.0001


# ── g2b_code 처리 ────────────────────────────────────────────────────────────

def test_g2b_code_stored_when_column_exists():
    row = {**BASE_ROW, "g2b분류": "C081"}
    path = make_csv([row])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["g2b_code"] == "C081"


def test_g2b_code_none_when_column_missing():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert len(df) == 1
    assert df.iloc[0]["g2b_code"] is None


# ── 기존 기능 회귀 테스트 ────────────────────────────────────────────────────

def test_participants_stored_correctly():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert df.iloc[0]["participants"] == 42


def test_lower_limit_rate_converted_from_percent():
    """낙찰하한율 87.745 → 0.87745 변환 확인."""
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert abs(float(df.iloc[0]["lower_limit_rate"]) - 0.87745) < 0.000001


def test_region_stored_correctly():
    path = make_csv([BASE_ROW])
    df = extract_and_transform(path)
    assert df.iloc[0]["region"] == "경기"
```

- [ ] **Step 2: 테스트 실행 — 전부 실패 확인**

```bash
cd c:\Users\Lenovo\gonggong
pytest tests/test_etl_csv.py -v
```

Expected: `normalize_price_method` import 에러 또는 관련 테스트들 FAIL

- [ ] **Step 3: etl_csv.py 수정 — normalize_price_method 추가**

`scripts/etl_csv.py`에서 `normalize_bid_type` 함수 다음에 추가:

```python
# ── 예정가격결정방식 정규화 ────────────────────────────────────────────────────
def normalize_price_method(raw: str) -> str:
    """'복수예비가격' / '고정예정가격' 외 → '기타'"""
    if not raw or pd.isna(raw):
        return "기타"
    raw = str(raw).strip()
    if "복수예비가격" in raw:
        return "복수예비가격"
    if "고정예정가격" in raw:
        return "고정예정가격"
    return "기타"
```

- [ ] **Step 4: etl_csv.py 수정 — records.append 블록 교체**

`extract_and_transform` 함수 내 `records.append({...})` 블록을 아래로 교체한다.

변경 전:
```python
            records.append({
                "project_id":       str(row["입찰공고번호"]).strip(),
                "client_name":      str(row.get("수요기관", "")).strip() or None,
                "client_id":        str(row.get("수요기관사업자등록번호", "")).strip() or None,
                "region":           normalize_region(row.get("수요기관지역", "")),
                "project_type":     project_type,
                "bid_type":         normalize_bid_type(row.get("낙찰방법", "")),
                "base_price":       base_price,
                "lower_limit_rate": lower_limit,
                "adjustment_rate":  adjustment_rate,
                "winner_price":     winner_price,
                "participants":     participants,
                "bid_date":         bid_date,
            })
```

변경 후:
```python
            # ── price_method ───────────────────────────────────────────
            raw_pm = row.get("예정가격결정방식", "")
            price_method = normalize_price_method(str(raw_pm) if raw_pm else "")

            # ── 1순위사정율: 있으면 직접 사용, 없으면 예산가격/기초금액 ──────
            raw_sar = row.get("1순위사정율", None)
            if raw_sar is not None and str(raw_sar).strip() not in ("", "nan"):
                sar = float(str(raw_sar).replace(",", "").strip())
                if sar > 1:      # 퍼센트 단위 (예: 99.71) → 소수
                    sar = sar / 100.0
                adjustment_rate = sar
            # adjustment_rate는 이미 위에서 est_price/base_price로 계산됨
            # 1순위사정율이 있으면 덮어쓴다

            # ── g2b_code ───────────────────────────────────────────────
            raw_g2b = row.get("g2b분류", None)
            g2b_code = str(raw_g2b).strip() if raw_g2b and str(raw_g2b).strip() not in ("", "nan") else None

            records.append({
                "project_id":       str(row["입찰공고번호"]).strip(),
                "client_name":      str(row.get("수요기관", "")).strip() or None,
                "client_id":        str(row.get("수요기관사업자등록번호", "")).strip() or None,
                "region":           normalize_region(row.get("수요기관지역", "")),
                "project_type":     project_type,
                "bid_type":         normalize_bid_type(row.get("낙찰방법", "")),
                "price_method":     price_method,
                "base_price":       base_price,
                "lower_limit_rate": lower_limit,
                "adjustment_rate":  adjustment_rate,
                "winner_price":     winner_price,
                "participants":     participants,
                "bid_date":         bid_date,
                "g2b_code":         g2b_code,
            })
```

- [ ] **Step 5: etl_csv.py 수정 — load_to_db의 session.add 블록에 신규 필드 추가**

`load_to_db` 함수에서 `session.add(BidsHistory(...))` 블록에 두 필드 추가:

```python
            session.add(BidsHistory(
                project_id       = row["project_id"],
                client_name      = row["client_name"],
                client_id        = row["client_id"],
                region           = row["region"],
                project_type     = row["project_type"],
                bid_type         = row["bid_type"],
                price_method     = row["price_method"],   # 추가
                base_price       = row["base_price"],
                lower_limit_rate = row["lower_limit_rate"],
                adjustment_rate  = row["adjustment_rate"],
                winner_price     = row["winner_price"],
                participants     = row["participants"],
                bid_date         = row["bid_date"],
                g2b_code         = row["g2b_code"],       # 추가
            ))
```

upsert 블록(`if upsert:`)에도 동일하게 추가:
```python
                    existing.price_method     = row["price_method"]   # 추가
                    existing.g2b_code         = row["g2b_code"]       # 추가
```

- [ ] **Step 6: 테스트 실행 — 전부 통과 확인**

```bash
pytest tests/test_etl_csv.py -v
```

Expected:
```
tests/test_etl_csv.py::test_normalize_price_method_복수예비가격 PASSED
tests/test_etl_csv.py::test_normalize_price_method_고정예정가격 PASSED
tests/test_etl_csv.py::test_normalize_price_method_unknown PASSED
tests/test_etl_csv.py::test_normalize_price_method_empty PASSED
tests/test_etl_csv.py::test_price_method_mapped_when_column_exists PASSED
tests/test_etl_csv.py::test_price_method_default_when_column_missing PASSED
tests/test_etl_csv.py::test_adjustment_rate_from_1순위사정율_when_column_exists PASSED
tests/test_etl_csv.py::test_adjustment_rate_computed_when_column_missing PASSED
tests/test_etl_csv.py::test_g2b_code_stored_when_column_exists PASSED
tests/test_etl_csv.py::test_g2b_code_none_when_column_missing PASSED
tests/test_etl_csv.py::test_participants_stored_correctly PASSED
tests/test_etl_csv.py::test_lower_limit_rate_converted_from_percent PASSED
tests/test_etl_csv.py::test_region_stored_correctly PASSED
```

- [ ] **Step 7: 기존 테스트 회귀 확인**

```bash
pytest tests/ -v --ignore=tests/test_api_bidding.py --ignore=tests/test_direct.py --ignore=tests/test_real_statistics.py -q
```

Expected: 기존 테스트 전부 PASS (DB 연결 필요한 테스트 제외)

- [ ] **Step 8: 커밋**

```bash
git add scripts/etl_csv.py tests/test_etl_csv.py
git commit -m "feat: ETL에 price_method, 1순위사정율, g2b_code 처리 추가"
```

---

## Task 3: validate_data.py 작성

**Files:**
- Create: `scripts/validate_data.py`

ETL 실행 후 데이터 품질을 자동 판정하는 스크립트. DB에 직접 연결하여 실행한다.

- [ ] **Step 1: validate_data.py 작성**

```python
"""
scripts/validate_data.py
ETL 적재 후 bids_history 데이터 품질 자동 검증.

사용법:
  python scripts/validate_data.py

판정:
  ✅ 백필 진행 가능   — 실패 항목 0개
  ⚠ 품질 주의        — 경고만 있는 경우
  ❌ 재수집 필요      — 실패 항목 1개 이상
"""

import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/gonggong").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# 지역명 화이트리스트 (단일 지역 또는 "전국,경기" 형식 조합)
REGION_WHITELIST = {
    "경기", "서울", "인천", "부산", "대구", "대전", "광주", "울산", "세종",
    "강원", "충남", "충북", "전남", "전북", "경남", "경북", "제주", "전국",
}


def is_valid_region(region: str) -> bool:
    """'전국,경기' 형식 포함 — 쉼표로 분리 후 각 파트가 화이트리스트에 있으면 유효."""
    parts = [p.strip() for p in region.split(",")]
    return all(p in REGION_WHITELIST for p in parts)


async def validate(conn) -> tuple[list[str], list[str]]:
    """(warnings, failures) 반환."""
    warnings = []
    failures = []
    total = await conn.fetchval("SELECT COUNT(*) FROM bids_history")

    if total == 0:
        failures.append("bids_history가 비어있음 — ETL을 먼저 실행하세요")
        return warnings, failures

    print(f"\n총 레코드: {total}건\n")

    # ── 1. participants ────────────────────────────────────────────────────
    zero_p = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE participants = 0"
    )
    zero_pct = zero_p / total * 100
    print(f"[participants] 0인 비율: {zero_pct:.1f}% ({zero_p}/{total})")
    if zero_pct >= 80:
        failures.append(f"participants=0 비율 {zero_pct:.1f}% — 상세 포맷 컬럼 누락 의심")
    elif zero_pct >= 30:
        warnings.append(f"participants=0 비율 {zero_pct:.1f}% — 일부 데이터 누락")

    # ── 2. lower_limit_rate ───────────────────────────────────────────────
    fixed_llr = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE lower_limit_rate = 0.877450"
    )
    fixed_pct = fixed_llr / total * 100
    print(f"[lower_limit_rate] 0.87745 고정 비율: {fixed_pct:.1f}% ({fixed_llr}/{total})")
    if fixed_pct >= 90:
        failures.append(f"lower_limit_rate 고정값 비율 {fixed_pct:.1f}% — 요약 포맷 의심")
    elif fixed_pct >= 50:
        warnings.append(f"lower_limit_rate 고정값 비율 {fixed_pct:.1f}%")

    # ── 3. region ──────────────────────────────────────────────────────────
    regions = await conn.fetch(
        "SELECT DISTINCT region FROM bids_history"
    )
    invalid_regions = [r["region"] for r in regions if not is_valid_region(r["region"])]
    invalid_count = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE region = ANY($1::text[])",
        invalid_regions if invalid_regions else ["__NEVER_MATCH__"],
    )
    invalid_pct = invalid_count / total * 100
    print(f"[region] 화이트리스트 외 값 비율: {invalid_pct:.1f}% ({invalid_count}/{total})")
    if invalid_regions:
        print(f"  의심 값 샘플: {invalid_regions[:5]}")
    if invalid_pct >= 50:
        failures.append(f"region 의심값 비율 {invalid_pct:.1f}% — 요약 포맷 의심")
    elif invalid_pct >= 20:
        warnings.append(f"region 의심값 비율 {invalid_pct:.1f}%")

    # ── 4. adjustment_rate 범위 ───────────────────────────────────────────
    out_of_range = await conn.fetchval(
        "SELECT COUNT(*) FROM bids_history WHERE adjustment_rate < 0.95 OR adjustment_rate > 1.05"
    )
    oor_pct = out_of_range / total * 100
    print(f"[adjustment_rate] 0.95~1.05 범위 외: {oor_pct:.1f}% ({out_of_range}/{total})")
    if oor_pct >= 5:
        failures.append(f"adjustment_rate 범위 이탈 {oor_pct:.1f}%")
    elif oor_pct >= 1:
        warnings.append(f"adjustment_rate 범위 이탈 {oor_pct:.1f}%")

    # ── 5. price_method 분포 (판정 없음, 정보 출력만) ─────────────────────
    pm_dist = await conn.fetch(
        "SELECT price_method, COUNT(*) as cnt FROM bids_history GROUP BY price_method ORDER BY cnt DESC"
    )
    print(f"[price_method] 분포:")
    for r in pm_dist:
        print(f"  {r['price_method']}: {r['cnt']}건 ({r['cnt']/total*100:.1f}%)")

    return warnings, failures


async def print_summary(conn, total: int):
    """추가 통계 출력."""
    print("\n─── 공종별 / 버킷별 분포 ───")
    pt = await conn.fetch(
        "SELECT project_type, COUNT(*) as cnt FROM bids_history GROUP BY project_type ORDER BY cnt DESC"
    )
    for r in pt:
        print(f"  {r['project_type']}: {r['cnt']}건")

    bucket_dist = await conn.fetch("""
        SELECT
            CASE
                WHEN base_price < 100000000 THEN '버킷1(<1억)'
                WHEN base_price < 500000000 THEN '버킷2(1억~5억)'
                WHEN base_price < 2000000000 THEN '버킷3(5억~20억)'
                ELSE '버킷4(20억+)'
            END as bucket,
            COUNT(*) as cnt
        FROM bids_history GROUP BY 1 ORDER BY 1
    """)
    for r in bucket_dist:
        print(f"  {r['bucket']}: {r['cnt']}건")

    print("\n─── adjustment_rate 히스토그램 ───")
    hist = await conn.fetch("""
        SELECT floor(adjustment_rate * 100)::int as pct, COUNT(*) as cnt
        FROM bids_history
        GROUP BY 1 ORDER BY 1
    """)
    for r in hist:
        bar = "█" * min(r["cnt"] // 5, 40)
        print(f"  {r['pct']}%: {bar} ({r['cnt']}건)")

    print("\n─── 발주처별 건수 Top 10 + 예상 Fallback 레벨 ───")
    top_clients = await conn.fetch("""
        SELECT client_name, COUNT(*) as cnt
        FROM bids_history
        GROUP BY client_name
        ORDER BY cnt DESC
        LIMIT 10
    """)
    for r in top_clients:
        cnt = r["cnt"]
        level = "client (Lv1)" if cnt >= 20 else f"region/bucket 이하 ({cnt}건, 20건 미달)"
        print(f"  {r['client_name']}: {cnt}건 → 예상 {level}")


async def main():
    conn = await asyncpg.connect(DB_URL)
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM bids_history")
        print("=" * 50)
        print("  bids_history 데이터 품질 검증")
        print("=" * 50)

        warnings, failures = await validate(conn)

        if total > 0:
            await print_summary(conn, total)

        print("\n" + "=" * 50)
        if failures:
            print("❌ 재수집 필요")
            for f in failures:
                print(f"  FAIL: {f}")
        elif warnings:
            print("⚠ 진행 가능하나 데이터 품질 주의")
            for w in warnings:
                print(f"  WARN: {w}")
        else:
            print("✅ 백필 진행 가능")
        print("=" * 50)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: is_valid_region 함수 단위 테스트 — tests/test_etl_csv.py에 추가**

`tests/test_etl_csv.py` 파일 끝에 추가:

```python
# ── validate_data.py 헬퍼 테스트 ─────────────────────────────────────────────
from scripts.validate_data import is_valid_region

def test_is_valid_region_단일():
    assert is_valid_region("경기") is True

def test_is_valid_region_조합():
    assert is_valid_region("전국,경기") is True

def test_is_valid_region_잘린_기관명():
    assert is_valid_region("(재") is False

def test_is_valid_region_국군():
    assert is_valid_region("국군") is False
```

- [ ] **Step 3: 테스트 실행 — 통과 확인**

```bash
pytest tests/test_etl_csv.py::test_is_valid_region_단일 tests/test_etl_csv.py::test_is_valid_region_조합 tests/test_etl_csv.py::test_is_valid_region_잘린_기관명 tests/test_etl_csv.py::test_is_valid_region_국군 -v
```

Expected: 4개 PASS

- [ ] **Step 4: 커밋**

```bash
git add scripts/validate_data.py tests/test_etl_csv.py
git commit -m "feat: 데이터 품질 검증 스크립트 추가 (validate_data.py)"
```

---

## Task 4: Phase 1 — 테스트 다운로드 및 검증 (수동 실행)

**Files:** 없음 (코드 변경 없음, 실행 단계)

- [ ] **Step 1: --debug 모드로 2025년 1월 실내건축 다운로드**

```bash
python scripts/info21c_downloader.py --start 20250101 --end 20250131 --type 0002 --debug
```

브라우저가 열리면 내보내기 다이얼로그에서 아래 컬럼 선택 확인:
- 필수: 입찰공고번호, 개찰순위, 면허업종제한목록, **낙찰하한율**, 기초금액, 예산가격, 투찰금액, **입찰참여자수**
- 추가: 투찰일자, 낙찰방법, 수요기관, **수요기관지역**, 수요기관사업자등록번호, 예정가격결정방식, **1순위사정율**, **g2b분류**

내보내기 옵션: CSV 형식, 리포트제목 OFF, 필터세부사항 OFF

- [ ] **Step 2: CSV 헤더 육안 확인**

다운로드된 파일을 열어 첫 행 확인:
```
입찰공고번호,개찰순위,면허업종제한목록,낙찰하한율,...
```
- 첫 행이 바로 헤더여야 함 (메타데이터 행 없어야 함)
- `낙찰하한율`, `입찰참여자수`, `수요기관지역` 컬럼 존재 확인

- [ ] **Step 3: ETL 실행**

```bash
python scripts/etl_csv.py --file data/downloads/info21c_0002_20250101_20250131.csv
```

Expected:
```
1. 파일 읽는 중: ...
  → 인코딩: utf-8-sig, 행 수: N
  → 1순위(낙찰자) 행: N건
  → 드롭: 값 오류 N건, 공종 미매핑 N건, 파싱 오류 N건
  → DB 적재 대상: N건
2. DB 적재 중...
  → 신규 N건 적재 / 기존 0건 스킵
```

- [ ] **Step 4: 조경 동일 반복**

```bash
python scripts/info21c_downloader.py --start 20250101 --end 20250131 --type 0023 --debug
python scripts/etl_csv.py --file data/downloads/info21c_0023_20250101_20250131.csv
```

- [ ] **Step 5: validate_data.py 실행 — 판정 확인**

```bash
python scripts/validate_data.py
```

Expected 최소 조건 (`✅ 백필 진행 가능` 출력):
- `participants=0` 비율 < 80%
- `lower_limit_rate` 고정 비율 < 90%
- `region` 의심값 비율 < 50%

`❌ 재수집 필요` 가 나오면: 어느 항목이 FAIL인지 확인 후 해당 컬럼 재선택 후 재다운로드

---

## Task 5: Phase 1 완료 — 2025~2026 전체 백필

**Files:** 없음 (실행 단계)

> Task 4에서 `✅ 백필 진행 가능` 판정을 받은 후 진행.

- [ ] **Step 1: 2025~2026 전체 자동 백필**

```bash
python scripts/backfill_info21c.py --start 2025 --end 2026 --type all
```

완료까지 수십 분 소요. 진행 상황이 콘솔에 월별로 출력됨:
```
[2025-01 실내건축] 45건 → 신규 32건 / 스킵 0건
[2025-01 조경] 18건 → 신규 14건 / 스킵 0건
...
```

100건 한계 도달 시 자동으로 주별 재분할 실행됨.

- [ ] **Step 2: 백필 완료 후 validate_data.py 재실행**

```bash
python scripts/validate_data.py
```

성공 기준:
- 총 레코드 수 500건 이상
- `✅ 백필 진행 가능` 판정
- 발주처별 Top 10 중 일부가 `client (Lv1)` 예상 레벨 도달

- [ ] **Step 3: Phase 2 — 2023~2024 확장 (선택)**

Phase 1 성공 확인 후 진행:

```bash
python scripts/backfill_info21c.py --start 2023 --end 2024 --type all
python scripts/validate_data.py
```

---

## 자체 검토 (Spec Coverage)

| 스펙 요구사항 | 구현 Task |
|---|---|
| DB TRUNCATE | Task 1 Step 5 |
| g2b_code 컬럼 추가 | Task 1 Step 1~4 |
| price_method 컬럼 매핑 | Task 2 Step 3~4 |
| 1순위사정율 처리 | Task 2 Step 4 |
| g2b_code ETL 처리 | Task 2 Step 4~5 |
| validate_data.py — participants 검증 | Task 3 |
| validate_data.py — lower_limit_rate 검증 | Task 3 |
| validate_data.py — region 화이트리스트 검증 | Task 3 |
| validate_data.py — adjustment_rate 범위 검증 | Task 3 |
| validate_data.py — price_method 분포 출력 | Task 3 |
| validate_data.py — fallback 시뮬레이션 | Task 3 |
| --debug 테스트 다운로드 | Task 4 |
| Phase 1 백필 (2025~2026) | Task 5 |
| Phase 2 백필 (2023~2024) | Task 5 Step 3 |
