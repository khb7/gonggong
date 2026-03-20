"""
app/jobs/collect.py
일별 수집 잡 — APScheduler 또는 직접 호출용.
"""

import logging
from datetime import date, timedelta

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.db.crud_write import upsert_bids_history
from app.external.g2b_collector import G2BCollector

logger = logging.getLogger(__name__)


async def run_daily_collect():
    """전날 하루치 낙찰결과 수집."""
    yesterday = date.today() - timedelta(days=1)
    await collect_range(yesterday, yesterday)


async def collect_range(start_date: date, end_date: date) -> int:
    """날짜 범위 수집 (backfill에서도 호출).
    이미 수집된 날짜가 포함된 청크는 건너뛴다.
    """
    from app.db.session import engine
    from app.db.crud import get_collected_dates

    async with AsyncSessionLocal() as db:
        collected = await get_collected_dates(db, start_date, end_date)

    collector = G2BCollector(api_key=settings.G2B_API_KEY)
    records = await collector.collect_range(start_date, end_date, skip_dates=collected)

    async with AsyncSessionLocal() as db:
        inserted, skipped = await upsert_bids_history(db, records)

    await engine.dispose()

    logger.info(
        f"수집 완료 {start_date}~{end_date}: "
        f"총 {len(records)}건, 신규 {inserted}건, 스킵 {skipped}건"
    )
    return inserted
