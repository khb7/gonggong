"""
app/db/crud_write.py
bids_history / bid_participants 쓰기 전용 CRUD.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BidsHistory, BidLicenseType, BidParticipants


async def upsert_bids_history(
    db: AsyncSession,
    records: list,
) -> tuple[int, int]:
    """
    레코드 목록을 bids_history에 삽입.
    project_id 중복은 스킵 (INSERT ON CONFLICT DO NOTHING).

    Returns:
        (inserted_count, skipped_count)
    """
    if not records:
        return 0, 0

    bid_values = [
        {
            "project_id": r.project_id,
            "client_name": r.client_name,
            "region": r.region,
            "base_price": r.base_price,
            "lower_limit_rate": r.lower_limit_rate,
            "adjustment_rate": r.adjustment_rate,
            "winner_price": r.winner_price,
            "participants": r.participants,
            "bid_date": r.bid_date,
            "bid_type": getattr(r, "bid_type", "기타"),
            "client_id": getattr(r, "client_id", None),
            "price_method": getattr(r, "price_method", "기타"),
        }
        for r in records
    ]

    stmt = pg_insert(BidsHistory).values(bid_values)
    stmt = stmt.on_conflict_do_nothing(index_elements=["project_id"])
    result = await db.execute(stmt)

    # G2B 수집 레코드는 project_type 단일 문자열 → BidLicenseType 1건 생성
    license_values = [
        {
            "project_id": r.project_id,
            "type_name": r.project_type,
            "size": None,
            "is_mutual": False,
            "is_primary": True,
        }
        for r in records
        if getattr(r, "project_type", None)
    ]
    if license_values:
        lt_stmt = pg_insert(BidLicenseType).values(license_values)
        lt_stmt = lt_stmt.on_conflict_do_nothing(index_elements=["project_id", "type_name"])
        await db.execute(lt_stmt)

    await db.commit()

    inserted = result.rowcount
    skipped = len(records) - inserted
    return inserted, skipped


async def upsert_bid_participants(
    db: AsyncSession,
    records: list[dict],
) -> tuple[int, int]:
    """
    전체 참여자 투찰 데이터를 bid_participants에 삽입.
    (project_id, rank) 중복은 스킵.

    Args:
        records: dict 리스트. 필수 키: project_id, rank, bid_amount, bid_rate, is_winner

    Returns:
        (inserted_count, skipped_count)
    """
    if not records:
        return 0, 0

    stmt = pg_insert(BidParticipants).values(records)
    stmt = stmt.on_conflict_do_nothing(
        constraint="uq_bid_participants_project_rank"
    )
    result = await db.execute(stmt)
    await db.commit()

    inserted = result.rowcount
    skipped = len(records) - inserted
    return inserted, skipped
