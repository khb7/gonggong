"""
tests/test_collect_window.py
app/jobs/collect_window.py — 수집할 날짜 구간 계산.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.models import BidsHistory, BidParticipants
from app.db.crud import get_collected_dates, get_participant_collected_dates
from app.jobs.collect_window import pending_ranges


def test_all_days_missing_becomes_one_range():
    """전부 미수집이면 한 구간으로 묶인다."""
    result = pending_ranges(set(), date(2026, 1, 1), date(2026, 1, 5))

    assert result == [(date(2026, 1, 1), date(2026, 1, 5))]


def test_collected_days_are_skipped():
    """이미 수집한 날짜는 빠지고, 남은 날짜만 구간이 된다.

    2026-01-01 은 목요일이다. 1/3(토)·1/4(일) 은 개찰이 없어 후보에서 빠지므로
    뒤 구간은 1/5(월) 하루뿐이다.
    """
    collected = {date(2026, 1, 2), date(2026, 1, 3)}

    result = pending_ranges(collected, date(2026, 1, 1), date(2026, 1, 5))

    assert result == [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2026, 1, 5), date(2026, 1, 5)),
    ]


def test_everything_collected_returns_empty():
    """빈 날짜가 없으면 아무것도 수집하지 않는다."""
    collected = {date(2026, 1, 1), date(2026, 1, 2)}

    result = pending_ranges(collected, date(2026, 1, 1), date(2026, 1, 2))

    assert result == []


def test_long_gap_is_split_by_max_span():
    """긴 공백은 max_span **평일** 단위로 잘린다.

    8 개월을 한 번에 주면 브라우저 세션이 버티지 못한다. 세션이 버티는 한계는
    달력 일수가 아니라 실제로 훑는 공고 양이므로 평일로 센다.

    2026-01-01(목) ~ 01-10(토), max_span=4:
        1/1 목  1/2 금  [1/3 토·1/4 일 건너뜀]  1/5 월  1/6 화   → 평일 4개
        1/7 수  1/8 목  1/9 금  [1/10 토 건너뜀]           → 평일 3개
    """
    result = pending_ranges(set(), date(2026, 1, 1), date(2026, 1, 10), max_span=4)

    assert result == [
        (date(2026, 1, 1), date(2026, 1, 6)),
        (date(2026, 1, 7), date(2026, 1, 9)),
    ]


# ──────────────────────────────────────────
# 참여자 기준 수집 이력
# ──────────────────────────────────────────

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


@pytest.mark.asyncio
async def test_collected_dates_returns_date_objects(db):
    """수집 이력은 date 객체로 돌아온다.

    func.distinct() 로 감싸면 SQLite 에서 문자열이 돌아오고, 호출부의
    `chunk_days.issubset(collected)` 가 영영 False 가 되어 스킵이 동작하지 않는다.
    """
    await _add_notice(db, "P1", date(2026, 1, 1))
    await db.commit()

    result = await get_collected_dates(db, date(2026, 1, 1), date(2026, 1, 1))

    assert result == {date(2026, 1, 1)}


# ── 주말 제외 ────────────────────────────────────────────────────────────────

def test_pending_ranges_skips_weekends():
    """토·일은 후보로 올리지 않는다.

    개찰은 평일에만 있다 — DB 전 기간(2023-12~2026-09) 요일별 공고 수:

        월 2,222  화 3,923  수 3,393  목 3,343  금 3,035
        토     0  일     0

    주말은 수집해도 결과가 없으니 `collected` 에도 영원히 안 들어가고,
    그래서 매 실행마다 미수집으로 다시 잡혀 브라우저 세션을 낭비한다.
    """
    # 2026-09-07(월) ~ 2026-09-13(일), 수집된 날 없음
    ranges = pending_ranges(set(), date(2026, 9, 7), date(2026, 9, 13))

    days = [d for a, b in ranges for d in _days(a, b)]
    assert date(2026, 9, 12) not in days, "토요일이 후보에 남았다"
    assert date(2026, 9, 13) not in days, "일요일이 후보에 남았다"
    assert days == [date(2026, 9, d) for d in range(7, 12)]


def test_pending_ranges_weekend_does_not_split_a_run():
    """주말이 평일 구간을 쪼개지 않는다.

    금요일과 다음 월요일은 이어진 구간으로 묶여야 한다 — 사이의 토·일은
    '수집할 것이 없는 날' 이지 '경계' 가 아니다. 쪼개면 브라우저 세션이
    구간마다 새로 뜬다.
    """
    # 2026-09-11(금) ~ 2026-09-14(월)
    ranges = pending_ranges(set(), date(2026, 9, 11), date(2026, 9, 14))

    assert len(ranges) == 1, f"주말이 구간을 쪼갰다: {ranges}"
    assert ranges[0] == (date(2026, 9, 11), date(2026, 9, 14))


def test_pending_ranges_all_weekend_returns_nothing():
    """주말만 조회하면 빈 결과 — 브라우저를 띄울 이유가 없다."""
    assert pending_ranges(set(), date(2026, 9, 12), date(2026, 9, 13)) == []


def _days(a: date, b: date) -> list[date]:
    out, cur = [], a
    while cur <= b:
        out.append(cur)
        cur += timedelta(days=1)
    return out
