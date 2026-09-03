# info21c 자동 수집 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PC 가 켜질 때마다 info21c 에서 아직 수집하지 않은 날짜만 골라 참여자 데이터를 받아온다.

**Architecture:** 날짜 구간 계산은 순수 함수로 분리해 테스트하고, 실제 수집은 이미 검증된 `scripts/info21c_participants.py` 의 `run()` 을 그대로 호출한다. 서버 APScheduler 가 아니라 **로컬 Windows 작업 스케줄러**가 진입점을 부른다.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 (async), Playwright, pytest (`asyncio_mode = auto`)

**Spec:** `docs/superpowers/specs/2026-08-25-my-bids-tracking-design.md` (Phase 1)

## Global Constraints

- 모든 비율은 `Decimal`, 모든 금액은 `int` (원 단위)
- 수집 대상 공종은 두 가지뿐: `0002`(실내건축), `0023`(조경) — `scripts/info21c_participants.py:LICENSE_TYPES`
- info21c 는 **동시 접속이 안 된다.** 공종 두 개를 병렬로 돌리지 말 것
- 기존 `app/jobs/collect.py`(G2B 경로)는 **건드리지 않는다.** `/api/v1/stats/backfill` 이 쓰고 있다

## 스펙과 달라지는 점 (실제 코드 확인 결과)

스펙은 `app/jobs/collect.py` 의 `G2BCollector` 를 info21c 로 교체한다고 적었다. 실제
코드를 보니 그 방향이 맞지 않는다.

- `app/jobs/collect.py` 는 FastAPI **서버**의 APScheduler 와 backfill API 가 함께 쓴다
- info21c 수집은 Playwright 로 브라우저를 띄우고, 실행 파일 경로가
  `C:\Program Files\BraveSoftware\...` 로 로컬 PC 를 전제한다 (`info21c_participants.py:409`)
- 서버(RAM 956MB, 여유 472MB)에서 Chromium 을 돌릴 수 없다

따라서 **`collect.py` 는 그대로 두고**, 로컬 전용 진입점을 따로 만든다. 스펙의 의도
("자동 수집을 info21c 로")는 그대로 지키되 붙는 자리만 바뀐다.

## File Structure

| 파일 | 책임 |
|---|---|
| `app/jobs/collect_window.py` (신규) | 수집할 날짜 구간 계산. 순수 함수, DB·네트워크 없음 |
| `app/db/crud.py` (수정) | 참여자 데이터가 실제로 들어온 날짜 조회 추가 |
| `scripts/daily_collect.py` (수정) | 로컬 진입점. 구간 계산 → 공종별 `run()` 호출 |
| `tests/test_collect_window.py` (신규) | 구간 계산 테스트 |
| `docs/deployment.md` (수정) | 작업 스케줄러 등록 절차 |

---

### Task 1: 수집할 날짜 구간 계산

수집 이력에서 빠진 날짜만 골라 연속 구간으로 묶는다. info21c 스크립트가
`--start`/`--end` 를 받으므로 구간 단위가 필요하고, 한 번에 너무 긴 구간을 주면
브라우저 세션이 버티지 못하므로 최대 길이로 자른다.

**Files:**
- Create: `app/jobs/collect_window.py`
- Test: `tests/test_collect_window.py`

**Interfaces:**
- Consumes: 없음 (순수 함수)
- Produces: `pending_ranges(collected: set[date], start: date, end: date, max_span: int = 7) -> list[tuple[date, date]]`

- [ ] **Step 1: Write the failing test**

`tests/test_collect_window.py`:

```python
"""
tests/test_collect_window.py
app/jobs/collect_window.py — 수집할 날짜 구간 계산.
"""

from datetime import date

from app.jobs.collect_window import pending_ranges


def test_all_days_missing_becomes_one_range():
    """전부 미수집이면 한 구간으로 묶인다."""
    result = pending_ranges(set(), date(2026, 1, 1), date(2026, 1, 5))

    assert result == [(date(2026, 1, 1), date(2026, 1, 5))]


def test_collected_days_are_skipped():
    """이미 수집한 날짜는 빠지고, 남은 날짜만 구간이 된다."""
    collected = {date(2026, 1, 2), date(2026, 1, 3)}

    result = pending_ranges(collected, date(2026, 1, 1), date(2026, 1, 5))

    assert result == [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2026, 1, 4), date(2026, 1, 5)),
    ]


def test_everything_collected_returns_empty():
    """빈 날짜가 없으면 아무것도 수집하지 않는다."""
    collected = {date(2026, 1, 1), date(2026, 1, 2)}

    result = pending_ranges(collected, date(2026, 1, 1), date(2026, 1, 2))

    assert result == []


def test_long_gap_is_split_by_max_span():
    """긴 공백은 max_span 일 단위로 잘린다.

    8 개월을 한 번에 주면 브라우저 세션이 버티지 못한다.
    """
    result = pending_ranges(set(), date(2026, 1, 1), date(2026, 1, 10), max_span=4)

    assert result == [
        (date(2026, 1, 1), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 8)),
        (date(2026, 1, 9), date(2026, 1, 10)),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collect_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs.collect_window'`

- [ ] **Step 3: Write minimal implementation**

`app/jobs/collect_window.py`:

```python
"""
app/jobs/collect_window.py
수집할 날짜 구간 계산.

PC 가 며칠 꺼져 있어도 다음 실행 때 공백을 메우기 위해, 수집 이력에 없는
날짜만 골라 연속 구간으로 묶는다. DB 도 네트워크도 건드리지 않는다.
"""

from datetime import date, timedelta


def pending_ranges(
    collected: set[date],
    start: date,
    end: date,
    max_span: int = 7,
) -> list[tuple[date, date]]:
    """start~end 중 collected 에 없는 날짜를 연속 구간으로 묶어 돌려준다.

    Args:
        collected: 이미 수집이 끝난 날짜 집합
        start:     조회 시작일 (포함)
        end:       조회 종료일 (포함)
        max_span:  구간 하나의 최대 일수. 긴 공백을 한 번에 넘기면
                   브라우저 세션이 버티지 못하므로 잘라 준다.

    Returns:
        [(구간시작, 구간끝), ...] — 빈 날짜가 없으면 빈 리스트
    """
    ranges: list[tuple[date, date]] = []
    current = start
    run_start: date | None = None
    run_len = 0

    def close():
        nonlocal run_start, run_len
        if run_start is not None:
            ranges.append((run_start, run_start + timedelta(days=run_len - 1)))
            run_start = None
            run_len = 0

    while current <= end:
        if current in collected:
            close()
        else:
            if run_start is None:
                run_start = current
                run_len = 0
            run_len += 1
            if run_len == max_span:
                close()
        current += timedelta(days=1)

    close()
    return ranges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collect_window.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/jobs/collect_window.py tests/test_collect_window.py
git commit -m "feat: 수집할 날짜 구간 계산 추가

PC 가 며칠 꺼져 있어도 다음 실행 때 공백을 메우도록, 수집 이력에 없는
날짜만 골라 연속 구간으로 묶는다. 긴 공백은 max_span 으로 자른다."
```

---

### Task 2: 참여자 데이터가 들어온 날짜 조회

Task 1 의 `collected` 를 채울 값을 DB 에서 가져온다.

기존 `get_collected_dates()` 는 `bids_history` 만 본다. info21c 수집의 목적은
`bid_participants`(개별 투찰가)이고, 공고는 있는데 참여자가 없는 날이 실제로 있다.
`bids_history` 기준으로 판단하면 그런 날을 "수집됨"으로 착각해 영영 건너뛴다.

**Files:**
- Modify: `app/db/crud.py` (파일 끝에 추가)
- Test: `tests/test_collect_window.py` (파일 끝에 추가)

**Interfaces:**
- Consumes: `app.db.models.BidsHistory`, `app.db.models.BidParticipants`
- Produces: `async def get_participant_collected_dates(db: AsyncSession, start_date: date, end_date: date) -> set[date]`

- [ ] **Step 1: Write the failing test**

`tests/test_collect_window.py` 끝에 추가. 파일 상단 import 도 함께 바꾼다:

```python
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.models import BidsHistory, BidParticipants
from app.db.crud import get_participant_collected_dates
from app.jobs.collect_window import pending_ranges
```

```python
@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _add_notice(session, project_id: str, bid_date: date):
    session.add(
        BidsHistory(
            project_id=project_id,
            client_name="테스트발주처",
            region="경기",
            base_price=800_000_000,
            lower_limit_rate=Decimal("0.87745"),
            adjustment_rate=Decimal("0.999"),
            winner_price=700_000_000,
            participants=40,
            bid_date=bid_date,
        )
    )


@pytest.mark.asyncio
async def test_date_without_participants_counts_as_not_collected(db):
    """공고만 있고 참여자가 없는 날은 미수집으로 본다.

    info21c 수집의 목적물은 bid_participants 다. bids_history 기준으로 판단하면
    참여자가 비어 있는 날을 수집됨으로 착각해 영영 건너뛴다.
    """
    await _add_notice(db, "WITH", date(2026, 1, 1))
    db.add(
        BidParticipants(
            project_id="WITH", rank=1, bid_amount=700_000_000,
            bid_rate=Decimal("0.88"), is_winner=True,
        )
    )
    await _add_notice(db, "WITHOUT", date(2026, 1, 2))  # 참여자 없음
    await db.commit()

    result = await get_participant_collected_dates(db, date(2026, 1, 1), date(2026, 1, 2))

    assert result == {date(2026, 1, 1)}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_collect_window.py::test_date_without_participants_counts_as_not_collected -v`
Expected: FAIL — `ImportError: cannot import name 'get_participant_collected_dates'`

- [ ] **Step 3: Write minimal implementation**

`app/db/crud.py` 끝에 추가:

```python
async def get_participant_collected_dates(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> set[date]:
    """start_date~end_date 중 참여자 데이터까지 들어온 날짜 집합을 반환한다.

    get_collected_dates() 와 달리 bid_participants 존재 여부를 본다.
    info21c 수집의 목적물이 개별 투찰가이므로, 공고만 있고 참여자가 비어 있는
    날은 아직 수집되지 않은 것으로 취급해야 한다.
    """
    from app.db.models import BidParticipants

    result = await db.execute(
        select(func.distinct(BidsHistory.bid_date))
        .join(BidParticipants, BidParticipants.project_id == BidsHistory.project_id)
        .where(
            BidsHistory.bid_date >= start_date,
            BidsHistory.bid_date <= end_date,
        )
    )
    return {row[0] for row in result.fetchall()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_collect_window.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/db/crud.py tests/test_collect_window.py
git commit -m "feat: 참여자 데이터가 들어온 날짜 조회 추가

info21c 수집의 목적물은 bid_participants 다. bids_history 기준으로 보면
공고만 있고 참여자가 빈 날을 수집됨으로 착각해 영영 건너뛴다."
```

---

### Task 3: 로컬 일별 수집 진입점

작업 스케줄러가 부르는 진입점. 빈 구간을 계산해 공종 두 개를 순차 수집한다.

**Files:**
- Modify: `scripts/daily_collect.py` (전체 교체)

**Interfaces:**
- Consumes: `pending_ranges()` (Task 1), `get_participant_collected_dates()` (Task 2),
  `scripts.info21c_participants.run(start_date: str, end_date: str, license_type: str, user_id: str, password: str, headless: bool) -> None`
- Produces: 없음 (진입점)

- [ ] **Step 1: 전체 교체**

`scripts/daily_collect.py`:

```python
"""
로컬 일별 수집 진입점 (Windows 작업 스케줄러용).

아직 참여자 데이터가 들어오지 않은 날짜만 골라 info21c 에서 받아온다.
PC 가 며칠 꺼져 있었어도 다음 실행 때 공백을 함께 메운다.

작업 스케줄러 설정은 docs/deployment.md 참조.

수동 실행:
    python scripts/daily_collect.py                # 최근 30일 중 빈 날짜
    python scripts/daily_collect.py --days 90      # 최근 90일
    python scripts/daily_collect.py --start 20251224 --end 20260131
"""

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.crud import get_participant_collected_dates
from app.db.session import AsyncSessionLocal, engine
from app.jobs.collect_window import pending_ranges
from scripts.info21c_participants import DEFAULT_ID, DEFAULT_PW, LICENSE_TYPES, run

# 한 번에 넘기는 최대 일수. 길면 브라우저 세션이 버티지 못한다.
MAX_SPAN = 7


def _parse_args():
    p = argparse.ArgumentParser(description="info21c 일별 참여자 수집")
    p.add_argument("--days", type=int, default=30, help="오늘로부터 며칠 전까지 볼지 (기본 30)")
    p.add_argument("--start", help="시작일 YYYYMMDD (--days 대신)")
    p.add_argument("--end", help="종료일 YYYYMMDD (--days 대신)")
    p.add_argument("--headless", action="store_true", help="브라우저 창 숨김")
    return p.parse_args()


def _window(args) -> tuple[date, date]:
    if args.start and args.end:
        return (
            datetime.strptime(args.start, "%Y%m%d").date(),
            datetime.strptime(args.end, "%Y%m%d").date(),
        )
    end = date.today() - timedelta(days=1)   # 어제까지. 오늘은 개찰이 안 끝났다
    return end - timedelta(days=args.days - 1), end


async def main_async(args) -> None:
    start, end = _window(args)
    print(f"조회 구간: {start} ~ {end}")

    async with AsyncSessionLocal() as db:
        collected = await get_participant_collected_dates(db, start, end)
    await engine.dispose()

    ranges = pending_ranges(collected, start, end, max_span=MAX_SPAN)
    if not ranges:
        print("빈 날짜 없음 — 수집할 것이 없다.")
        return

    total_days = sum((b - a).days + 1 for a, b in ranges)
    print(f"미수집 {total_days}일, {len(ranges)}개 구간")

    # info21c 는 동시 접속이 안 된다. 반드시 순차 실행.
    for i, (a, b) in enumerate(ranges, 1):
        for code, name in LICENSE_TYPES.items():
            print(f"\n[{i}/{len(ranges)}] {a}~{b} / {name}({code})", flush=True)
            try:
                await run(
                    start_date=a.strftime("%Y%m%d"),
                    end_date=b.strftime("%Y%m%d"),
                    license_type=code,
                    user_id=DEFAULT_ID,
                    password=DEFAULT_PW,
                    headless=args.headless,
                )
            except Exception as e:
                # 한 구간이 실패해도 나머지는 계속한다. 놓친 날짜는 다음 실행에서
                # 다시 미수집으로 잡히므로 따라잡힌다.
                print(f"  실패: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main_async(_parse_args()))
```

- [ ] **Step 2: 빈 날짜가 없을 때 브라우저를 띄우지 않는지 확인**

이미 수집이 끝난 좁은 구간을 준다. 로컬 DB 에 2025-05-01 은 데이터가 있다.

Run: `python scripts/daily_collect.py --start 20250501 --end 20250501`
Expected: `빈 날짜 없음 — 수집할 것이 없다.` 출력, 브라우저 창이 뜨지 않음

- [ ] **Step 3: 구간 계산이 맞는지 확인 (수집은 하지 않음)**

Run: `python scripts/daily_collect.py --start 20260801 --end 20260810`
Expected: `미수집 10일, 2개 구간` 출력 후 브라우저 기동 시작.
확인했으면 **Ctrl+C 로 중단한다** — 실제 수집은 Task 5 에서 한다.

- [ ] **Step 4: Commit**

```bash
git add scripts/daily_collect.py
git commit -m "feat: info21c 일별 수집 진입점

G2B 대신 info21c 를 부른다. G2B 수집은 참여자 수 정수 하나만 가져와
분포 엔진이 먹는 bid_participants 가 채워지지 않는다.

빈 날짜만 골라 순차 수집하므로 PC 가 며칠 꺼져 있어도 따라잡는다.
info21c 는 동시 접속이 안 돼 공종을 병렬로 돌리지 않는다."
```

---

### Task 4: 작업 스케줄러 등록 절차 문서화

**Files:**
- Modify: `docs/deployment.md` (파일 끝에 추가)

- [ ] **Step 1: 문서 추가**

`docs/deployment.md` 끝에 추가:

```markdown

---

## 9. 일별 데이터 수집 (로컬 PC)

info21c 는 Playwright 로 브라우저를 띄워 로그인하고 Excel 을 받는다. 서버는
RAM 이 부족하고(956MB 중 여유 472MB) info21c 가 동시 접속을 막으므로,
**수집은 로컬 PC 에서 돌리고 결과 DB 만 서버로 올린다.**

### 수동 실행

```bash
python scripts/daily_collect.py                     # 최근 30일 중 빈 날짜
python scripts/daily_collect.py --days 90           # 최근 90일
python scripts/daily_collect.py --start 20251224 --end 20260131
```

아직 참여자 데이터가 없는 날짜만 골라 받으므로, 여러 번 돌려도 중복 수집되지 않는다.

### 작업 스케줄러 등록

PC 를 매일 켜지 않아도 되도록 "놓친 작업 따라잡기"를 쓴다.

1. `작업 스케줄러` 실행 → **작업 만들기** (기본 작업 아님)
2. **일반** 탭 — 이름 `gonggong 일별 수집`, "사용자가 로그온할 때만 실행" 유지
3. **트리거** 탭 — 새로 만들기 → 매일 03:00
4. **동작** 탭 — 새로 만들기
   - 프로그램: `python`
   - 인수: `scripts/daily_collect.py --headless`
   - 시작 위치: `C:\Users\onebe\gonggong`
5. **설정** 탭 — **"예약된 시작을 놓친 경우 가능한 한 빨리 작업 시작"** 체크 ← 핵심
6. 확인

이 옵션 덕분에 PC 가 꺼져 있던 날의 작업은 다음에 켤 때 실행되고,
그때 빈 날짜를 한꺼번에 메운다.

### 첫 실행 주의

마지막 수집이 **2025-12-24** 라 공백이 길다. 한 번에 돌리면 오래 걸리므로
첫 회는 기간을 나눠 수동으로 돌린 뒤 스케줄러에 맡긴다.

```bash
python scripts/daily_collect.py --start 20251224 --end 20260131
python scripts/daily_collect.py --start 20260201 --end 20260331
# ... 이어서
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/deployment.md
git commit -m "docs: 일별 수집 실행법과 작업 스케줄러 등록 절차"
```

---

### Task 5: 실제 수집 1회 검증

계획의 마지막은 실제로 데이터가 들어오는지 보는 것이다. 짧은 구간으로 확인한다.

**Files:** 없음 (실행과 확인만)

- [ ] **Step 1: 수집 전 건수 기록**

```bash
python -c "import sqlite3; c=sqlite3.connect('data/gonggong.db'); print('participants:', c.execute('select count(*) from bid_participants').fetchone()[0]); print('공고수:', c.execute('select count(distinct project_id) from bid_participants').fetchone()[0])"
```

출력값을 적어 둔다.

- [ ] **Step 2: 3일치 수집**

Run: `python scripts/daily_collect.py --start 20251226 --end 20251228`

브라우저가 뜨고 로그인 후 목록을 훑는다. 로그인 실패나 셀렉터 오류가 나면
`data/downloads/_participants_etl.log` 를 확인한다.

- [ ] **Step 3: 건수가 늘었는지 확인**

Step 1 과 같은 명령을 다시 실행. `participants` 와 `공고수` 가 모두 늘어야 한다.
0 이면 그 기간에 해당 공종 공고가 없었을 수 있으니, 다른 구간으로 한 번 더 시도한다.

- [ ] **Step 4: 재실행 시 건너뛰는지 확인**

Run: `python scripts/daily_collect.py --start 20251226 --end 20251228`
Expected: `빈 날짜 없음 — 수집할 것이 없다.` — 브라우저가 뜨지 않는다

- [ ] **Step 5: 새로 들어온 데이터에 이상치가 있는지 확인**

```bash
python -c "import sqlite3; c=sqlite3.connect('data/gonggong.db'); q=lambda s:c.execute(s).fetchone()[0]; print('범위밖:', q('select count(*) from bid_participants where bid_rate <= 0.5 or bid_rate > 1.05'))"
```

이 값이 늘었다면 ETL 이 여전히 이상치를 넣고 있다는 뜻이다. 조회 시점에서는
막고 있으므로 화면은 정상이지만, `scripts/etl_participants.py` 수정이 여전히
남아 있음을 확인하는 용도다. 결과를 `eval-handoff.md` 에 적는다.

---

## 완료 조건

- `python scripts/daily_collect.py` 가 빈 날짜만 골라 수집한다
- 같은 구간을 두 번 돌리면 두 번째는 브라우저를 띄우지 않는다
- 작업 스케줄러에 등록돼 있고 "놓친 작업 따라잡기"가 켜져 있다
- `bid_participants` 건수가 실제로 늘었다
