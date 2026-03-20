"""
app/db/crud.py
DB 조회/저장 로직 (비동기 SQLAlchemy)
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BidsHistory, ClientStatistics

# Fallback 최소 샘플 수
MIN_SAMPLE_SIZE = 20

# bucket_id → (min_price, max_price) 매핑 (project_bucket 시드 데이터와 동기화)
_BUCKET_RANGES: dict[int, tuple[int, int | None]] = {
    1: (0,           100_000_000),
    2: (100_000_000, 500_000_000),
    3: (500_000_000, 2_000_000_000),
    4: (2_000_000_000, None),
}


def _bucket_filter(bucket_id: int):
    """
    bucket_id에 해당하는 base_price 범위 조건을 반환한다.
    Ref: 공공입찰.md - 1. 데이터 분리 (금액 구간)
    """
    min_p, max_p = _BUCKET_RANGES[bucket_id]
    if max_p is None:
        return BidsHistory.base_price >= min_p
    return and_(BidsHistory.base_price >= min_p, BidsHistory.base_price < max_p)


async def get_collected_dates(
    db: AsyncSession,
    start_date: date,
    end_date: date,
) -> set[date]:
    """start_date~end_date 범위 중 이미 수집된 날짜 집합 반환."""
    result = await db.execute(
        select(func.distinct(BidsHistory.bid_date)).where(
            BidsHistory.bid_date >= start_date,
            BidsHistory.bid_date <= end_date,
        )
    )
    return {row[0] for row in result.fetchall()}


async def get_rates_by_client(
    db: AsyncSession,
    client_name: str,
    project_type: str,
    bucket_id: int,
) -> list[Decimal]:
    """발주처 + 공종 + 버킷 기준 사정률 리스트 반환."""
    result = await db.execute(
        select(BidsHistory.adjustment_rate).where(
            BidsHistory.client_name == client_name,
            BidsHistory.project_type == project_type,
            _bucket_filter(bucket_id),
        )
    )
    return [row[0] for row in result.fetchall()]


async def get_rates_by_region(
    db: AsyncSession,
    region: str,
    project_type: str,
    bucket_id: int,
) -> list[Decimal]:
    """지역 + 공종 + 버킷 기준 사정률 리스트 반환."""
    result = await db.execute(
        select(BidsHistory.adjustment_rate).where(
            BidsHistory.region == region,
            BidsHistory.project_type == project_type,
            _bucket_filter(bucket_id),
        )
    )
    return [row[0] for row in result.fetchall()]


async def get_rates_by_type_and_bucket(
    db: AsyncSession,
    project_type: str,
    bucket_id: int,
) -> list[Decimal]:
    """공종 + 버킷 기준 사정률 리스트 반환."""
    result = await db.execute(
        select(BidsHistory.adjustment_rate).where(
            BidsHistory.project_type == project_type,
            _bucket_filter(bucket_id),
        )
    )
    return [row[0] for row in result.fetchall()]


async def get_all_rates(
    db: AsyncSession,
    project_type: str,
) -> list[Decimal]:
    """공종 전체 사정률 리스트 반환 (최후 Fallback, 버킷 구분 없음)."""
    result = await db.execute(
        select(BidsHistory.adjustment_rate).where(
            BidsHistory.project_type == project_type,
        )
    )
    return [row[0] for row in result.fetchall()]
