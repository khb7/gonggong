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

    1주일 청크 단위로 수집 후 즉시 DB에 저장한다.
    중간에 끊겨도 완료된 청크는 보존되며, 재실행 시 해당 날짜를 스킵한다.
    """
    from app.db.crud import get_collected_dates
    from app.db.session import engine

    total_inserted = 0
    total_days = (end_date - start_date).days + 1
    total_chunks = (total_days + 6) // 7
    chunk_num = 0
    current = start_date

    import httpx
    timeout = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=60.0)

    async with httpx.AsyncClient(timeout=timeout) as http_client:
        collector = G2BCollector(api_key=settings.G2B_API_KEY)

        while current <= end_date:
            chunk_end = min(current + timedelta(days=6), end_date)
            chunk_num += 1

            # 이미 수집된 날짜 확인 (청크 단위로 매번 조회해 재실행 시 최신 반영)
            async with AsyncSessionLocal() as db:
                collected = await get_collected_dates(db, current, chunk_end)

            chunk_days = {current + timedelta(days=i)
                          for i in range((chunk_end - current).days + 1)}
            if chunk_days.issubset(collected):
                print(f"[{chunk_num}/{total_chunks}] {current} ~ {chunk_end} 이미 수집됨, 스킵", flush=True)
                current = chunk_end + timedelta(days=1)
                continue

            print(f"[{chunk_num}/{total_chunks}] {current} ~ {chunk_end} 수집 중...", flush=True)
            records = await collector._collect_chunk(http_client, current, chunk_end)

            if records:
                async with AsyncSessionLocal() as db:
                    inserted, skipped = await upsert_bids_history(db, records)
                total_inserted += inserted
                print(f"  → {inserted}건 저장 (스킵 {skipped}건) / 누적 {total_inserted}건", flush=True)
            else:
                print(f"  → 0건", flush=True)

            current = chunk_end + timedelta(days=1)

    await engine.dispose()
    logger.info(f"수집 완료 {start_date}~{end_date}: 신규 {total_inserted}건")
    return total_inserted
