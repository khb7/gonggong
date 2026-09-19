"""
tests/test_crud_collect.py
app/db/crud_collect.py — info21c 수집 leg 의 DB 쓰기 검증 (T-035).

in-memory SQLite 에 넣고 다시 읽는다. crud_write.py 는 Postgres 전용 upsert 라
SQLite 로컬 DB 에서 못 쓰므로 수집 경로의 쓰기는 여기서 따로 검증한다.
"""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.models import (
    BidsHistory, BidParticipants, BidPreliminaryPrice, BidNoticeOpen, BidFinalAward,
)
from app.db.crud_collect import (
    save_participant_workbook, upsert_open_notice, upsert_final_award,
)
from app.etl.participant_excel import parse_participant_workbook
from app.etl.info21c_notice import OpenNotice
from app.etl.info21c_final_awards import FinalAward

FIXTURES = Path(__file__).parent / "fixtures"
PID = "R25BK00812461-000"


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _add_notice(session, *, est_price: int, a_value: int):
    session.add(BidsHistory(
        project_id=PID, client_name="경기도 남양주시 공원녹지관리사업소", region="경기",
        base_price=170_984_000, lower_limit_rate=Decimal("0.87745"),
        adjustment_rate=Decimal("0.8846"), winner_price=151_259_200, participants=3,
        bid_date=date(2025, 5, 1), bid_type="적격심사", price_method="복수예비가격",
        est_price=est_price, a_value=a_value, legal_limit_rate=Decimal("0.87745"),
    ))
    await session.commit()


@pytest.fixture(scope="module")
def wb():
    return parse_participant_workbook(FIXTURES / "participants_multi.xlsx")


# ── 참여자 워크북 ────────────────────────────────────────────────────────────

async def test_participants_inserted_with_company_identity(db, wb):
    await _add_notice(db, est_price=169_711_075, a_value=6_784_255)
    res = await save_participant_workbook(db, wb)
    assert res.participants_inserted == 3

    rows = (await db.execute(
        select(BidParticipants).where(BidParticipants.project_id == PID).order_by(BidParticipants.rank)
    )).scalars().all()
    assert [r.rank for r in rows] == [1, 2, 4]
    assert rows[0].company_id == "4538801481"
    assert rows[0].company_name == "(주)대경조경"
    assert rows[0].ceo_name == "최옥희"
    assert rows[0].is_winner is True and rows[1].is_winner is False


async def test_bid_rate_recomputed_from_amount_when_notice_known(db, wb):
    # (151,259,200 − 6,784,255) / (169,711,075 − 6,784,255) = 0.886747…
    await _add_notice(db, est_price=169_711_075, a_value=6_784_255)
    await save_participant_workbook(db, wb)
    r = (await db.execute(
        select(BidParticipants).where(BidParticipants.project_id == PID, BidParticipants.rank == 1)
    )).scalar_one()
    assert abs(r.bid_rate - Decimal("0.886747")) < Decimal("0.000002")


async def test_bid_rate_falls_back_to_source_without_notice(db, wb):
    await save_participant_workbook(db, wb)
    r = (await db.execute(
        select(BidParticipants).where(BidParticipants.project_id == PID, BidParticipants.rank == 1)
    )).scalar_one()
    assert r.bid_rate == Decimal("0.886747")


async def test_estimated_price_written_to_notice(db, wb):
    await _add_notice(db, est_price=169_711_075, a_value=6_784_255)
    await save_participant_workbook(db, wb)
    n = (await db.execute(select(BidsHistory).where(BidsHistory.project_id == PID))).scalar_one()
    assert n.estimated_price == 155_440_000


async def test_preliminary_prices_written_with_selection(db, wb):
    await save_participant_workbook(db, wb)
    ps = (await db.execute(
        select(BidPreliminaryPrice).where(BidPreliminaryPrice.project_id == PID)
        .order_by(BidPreliminaryPrice.num)
    )).scalars().all()
    assert len(ps) == 15
    assert [p.num for p in ps if p.is_selected] == [1, 4, 8, 10]
    assert ps[0].price == 166_894_100


async def test_second_save_backfills_company_columns_only(db, wb):
    """이미 적재된 행(순위·금액만 있는 과거분)은 업체 컬럼만 채우고 금액은 건드리지 않는다."""
    db.add(BidParticipants(project_id=PID, rank=1, bid_amount=999, bid_rate=Decimal("0.5"), is_winner=True))
    await db.commit()
    res = await save_participant_workbook(db, wb)
    assert res.participants_inserted == 2
    assert res.participants_backfilled == 1
    r = (await db.execute(
        select(BidParticipants).where(BidParticipants.project_id == PID, BidParticipants.rank == 1)
    )).scalar_one()
    assert r.bid_amount == 999
    assert r.company_id == "4538801481"


async def test_second_save_is_idempotent(db, wb):
    await save_participant_workbook(db, wb)
    res = await save_participant_workbook(db, wb)
    assert res.participants_inserted == 0
    assert res.participants_backfilled == 0
    ps = (await db.execute(select(BidPreliminaryPrice).where(BidPreliminaryPrice.project_id == PID))).scalars().all()
    assert len(ps) == 15


# ── 개찰 전 공고 ─────────────────────────────────────────────────────────────

def _notice(**over) -> OpenNotice:
    base = dict(
        project_id="R26BK01737250-001", notice_title="갈매수변공원", client_name="경기도 구리시",
        demand_org="경기도 구리시", region="경기", license_text="조경(식재.시설물)[대]",
        contract_method="수의", price_method="복수예비가격", preprice_range_pct=3,
        legal_limit_rate=Decimal("0.89745"), a_value=5_904_323, base_price=155_087_000,
        estimated_price=140_988_182, bid_close_at=datetime(2026, 9, 28, 12, 0),
        open_at=datetime(2026, 9, 28, 14, 0),
    )
    base.update(over)
    return OpenNotice(**base)


async def test_open_notice_insert_then_update(db):
    await upsert_open_notice(db, _notice(legal_limit_rate=None), info21c_bidid="2609-1")
    await upsert_open_notice(db, _notice(), info21c_bidid="2609-1")
    rows = (await db.execute(select(BidNoticeOpen))).scalars().all()
    assert len(rows) == 1
    assert rows[0].legal_limit_rate == Decimal("0.89745")
    assert rows[0].a_value == 5_904_323
    assert rows[0].preprice_range_pct == 3
    assert rows[0].info21c_bidid == "2609-1"


async def test_open_notice_update_does_not_erase_known_values_with_none(db):
    """재수집 때 페이지에서 값이 잠깐 빠져도 이미 아는 하한율·기초금액을 지우지 않는다."""
    await upsert_open_notice(db, _notice(), info21c_bidid=None)
    await upsert_open_notice(db, _notice(legal_limit_rate=None, base_price=None), info21c_bidid=None)
    row = (await db.execute(select(BidNoticeOpen))).scalar_one()
    assert row.legal_limit_rate == Decimal("0.89745")
    assert row.base_price == 155_087_000


# ── 최종낙찰현황 ─────────────────────────────────────────────────────────────

async def test_final_award_upsert(db):
    a = FinalAward(
        project_id="R26BK01728000-000", notice_title="가든샵", client_name="국립세종수목원",
        open_date=date(2026, 9, 18), award_amount=218_283_700, company_name="주식회사 디큐종합건설",
        ceo_name="김남규", address="서울", info21c_bidid="260914155214064-00-00-01",
    )
    await upsert_final_award(db, a)
    a.company_name = "정정된 업체"
    await upsert_final_award(db, a)
    rows = (await db.execute(select(BidFinalAward))).scalars().all()
    assert len(rows) == 1
    assert rows[0].company_name == "정정된 업체"
    assert rows[0].award_amount == 218_283_700
