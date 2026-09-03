"""
tests/test_collect_window.py
app/jobs/collect_window.py — 수집할 날짜 구간 계산.
"""

from datetime import date
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
