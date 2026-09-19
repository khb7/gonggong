"""
app/db/crud_collect.py
info21c 수집 leg 의 DB 쓰기 (T-035).

crud_write.py 는 Postgres 전용 `ON CONFLICT` upsert 라 로컬 SQLite 에서 못 쓴다.
수집은 로컬(SQLite)에서 돌고 DB 파일째 서버로 올리므로, 여기는 방언에 기대지
않는 select → insert/update 로 쓴다. 행 수가 공고당 수백~수천이라 충분하다.

세 가지를 쓴다:
  - save_participant_workbook : 참여자 Excel 한 장 → bid_participants (업체 식별자 포함)
                                + bids_history.estimated_price + bid_preliminary_prices
  - upsert_open_notice        : 개찰 전 공고 → bid_notices_open
  - upsert_final_award        : 최종낙찰현황 → bid_final_awards
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BidsHistory, BidParticipants, BidPreliminaryPrice, BidNoticeOpen, BidFinalAward,
)
from app.engine.a_value import bid_rate_with_a_value
from app.etl.participant_excel import ParticipantWorkbook
from app.etl.info21c_notice import OpenNotice
from app.etl.info21c_final_awards import FinalAward


@dataclass
class SaveResult:
    participants_inserted: int = 0
    participants_backfilled: int = 0
    preliminary_inserted: int = 0
    estimated_price_set: bool = False


async def save_participant_workbook(
    session: AsyncSession,
    wb: ParticipantWorkbook,
    *,
    project_id: str | None = None,
) -> SaveResult:
    """참여자 워크북 한 장을 적재한다. 몇 번 돌려도 같은 결과다.

    - 새 (project_id, rank) 는 삽입. 투찰율은 예정가격·A값을 알면 **투찰금액에서
      재계산**한다 (T-033: 원본 컬럼은 7.9% 공고에서 전 행이 어긋난다).
    - 이미 있는 행은 업체 컬럼이 비어 있을 때만 채운다. 금액·투찰율은 건드리지
      않는다 — 과거 적재분에 대한 백필 경로다.
    - 추정가격은 bids_history 에 없을 때만 넣는다.
    - 복수예가는 (project_id, num) 이 없을 때만 넣는다.
    """
    pid = project_id or wb.project_id
    res = SaveResult()

    notice = (await session.execute(
        select(BidsHistory).where(BidsHistory.project_id == pid)
    )).scalar_one_or_none()
    est_price = int(notice.est_price or 0) if notice else 0
    a_value = int(notice.a_value or 0) if notice else 0

    existing = {
        r.rank: r for r in (await session.execute(
            select(BidParticipants).where(BidParticipants.project_id == pid)
        )).scalars().all()
    }

    for row in wb.rows:
        cur = existing.get(row.rank)
        if cur is not None:
            if cur.company_id is None and row.company_id is not None:
                cur.company_id = row.company_id
                cur.company_name = row.company_name
                cur.ceo_name = row.ceo_name
                res.participants_backfilled += 1
            continue
        rate = bid_rate_with_a_value(row.bid_amount, est_price, a_value) or row.bid_rate
        session.add(BidParticipants(
            project_id=pid,
            rank=row.rank,
            bid_amount=row.bid_amount,
            bid_rate=rate,
            is_winner=(row.rank == 1),
            company_id=row.company_id,
            company_name=row.company_name,
            ceo_name=row.ceo_name,
        ))
        res.participants_inserted += 1

    if notice is not None and notice.estimated_price is None and wb.estimated_price:
        notice.estimated_price = wb.estimated_price
        res.estimated_price_set = True

    if wb.preliminary_prices:
        have = set((await session.execute(
            select(BidPreliminaryPrice.num).where(BidPreliminaryPrice.project_id == pid)
        )).scalars().all())
        for p in wb.preliminary_prices:
            if p.num in have:
                continue
            session.add(BidPreliminaryPrice(
                project_id=pid, num=p.num, price=p.price,
                base_pct=p.base_pct, is_selected=p.is_selected,
            ))
            res.preliminary_inserted += 1

    await session.commit()
    return res


# 재수집 때 None 으로 와도 이미 아는 값을 지우지 않는 컬럼.
# 하한율·A값·금액은 발표가 늦어 공고 초기엔 비어 있다가 나중에 채워진다.
_KEEP_IF_NONE = (
    "legal_limit_rate", "base_price", "estimated_price", "bid_close_at", "open_at",
    "client_name", "demand_org", "region", "license_text", "contract_method",
    "preprice_range_pct", "notice_title",
)


async def upsert_open_notice(
    session: AsyncSession, n: OpenNotice, *, info21c_bidid: str | None
) -> bool:
    """개찰 전 공고 한 건. 반환값은 '새로 삽입했는가'."""
    row = await session.get(BidNoticeOpen, n.project_id)
    values = dict(
        notice_title=n.notice_title, client_name=n.client_name, demand_org=n.demand_org,
        region=n.region, license_text=n.license_text, contract_method=n.contract_method,
        price_method=n.price_method, preprice_range_pct=n.preprice_range_pct,
        legal_limit_rate=n.legal_limit_rate, a_value=n.a_value, base_price=n.base_price,
        estimated_price=n.estimated_price, bid_close_at=n.bid_close_at, open_at=n.open_at,
    )
    inserted = row is None
    if row is None:
        row = BidNoticeOpen(project_id=n.project_id, info21c_bidid=info21c_bidid, **values)
        session.add(row)
    else:
        for k, v in values.items():
            if v is None and k in _KEEP_IF_NONE:
                continue
            if k == "a_value" and v == 0 and row.a_value:
                continue
            setattr(row, k, v)
        if info21c_bidid:
            row.info21c_bidid = info21c_bidid
    await session.commit()
    return inserted


async def upsert_final_award(session: AsyncSession, a: FinalAward) -> bool:
    row = await session.get(BidFinalAward, a.project_id)
    values = dict(
        info21c_bidid=a.info21c_bidid, notice_title=a.notice_title, client_name=a.client_name,
        open_date=a.open_date, award_amount=a.award_amount, company_name=a.company_name,
        ceo_name=a.ceo_name, address=a.address,
    )
    inserted = row is None
    if row is None:
        session.add(BidFinalAward(project_id=a.project_id, **values))
    else:
        for k, v in values.items():
            if v is not None:
                setattr(row, k, v)
    await session.commit()
    return inserted
