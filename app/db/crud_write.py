"""
app/db/crud_write.py
bids_history 쓰기 전용 CRUD.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BidsHistory


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

    values = [
        {
            "project_id": r.project_id,
            "client_name": r.client_name,
            "region": r.region,
            "project_type": r.project_type,
            "base_price": r.base_price,
            "lower_limit_rate": r.lower_limit_rate,
            "adjustment_rate": r.adjustment_rate,
            "winner_price": r.winner_price,
            "participants": r.participants,
            "bid_date": r.bid_date,
        }
        for r in records
    ]

    stmt = pg_insert(BidsHistory).values(values)
    stmt = stmt.on_conflict_do_nothing(index_elements=["project_id"])
    result = await db.execute(stmt)
    await db.commit()

    inserted = result.rowcount
    skipped = len(records) - inserted
    return inserted, skipped
