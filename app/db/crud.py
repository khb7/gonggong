"""
app/db/crud.py
DB 조회/저장 로직 (비동기 SQLAlchemy)
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BidsHistory, BidLicenseType, ClientStatistics

# Fallback 최소 샘플 수
MIN_SAMPLE_SIZE = 20

# 통계 대상 입찰방식 (적격심사만 사용)
TARGET_BID_TYPE = "적격심사"

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
    """
    min_p, max_p = _BUCKET_RANGES[bucket_id]
    if max_p is None:
        return BidsHistory.base_price >= min_p
    return and_(BidsHistory.base_price >= min_p, BidsHistory.base_price < max_p)


def _bid_type_filter(bid_type: str):
    """입찰방식 필터."""
    return BidsHistory.bid_type == bid_type


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
    bid_type: str = TARGET_BID_TYPE,
    client_id: str | None = None,
    before_date: date | None = None,
) -> list[Decimal]:
    """
    발주처 + 공종 + 버킷 기준 사정률 리스트 반환.
    client_id가 있으면 코드 우선, 없으면 client_name으로 매칭.
    before_date가 있으면 해당 날짜 이전 데이터만 조회 (백테스트용).
    """
    if client_id:
        client_filter = BidsHistory.client_id == client_id
    else:
        client_filter = BidsHistory.client_name == client_name

    conditions = [
        client_filter,
        BidLicenseType.type_name == project_type,
        _bucket_filter(bucket_id),
        _bid_type_filter(bid_type),
    ]
    if before_date is not None:
        conditions.append(BidsHistory.bid_date < before_date)

    result = await db.execute(
        select(BidsHistory.adjustment_rate)
        .join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
        .where(*conditions)
    )
    return [row[0] for row in result.fetchall()]


async def get_rates_by_region(
    db: AsyncSession,
    region: str,
    project_type: str,
    bucket_id: int,
    bid_type: str = TARGET_BID_TYPE,
    before_date: date | None = None,
) -> list[Decimal]:
    """지역 + 공종 + 버킷 기준 사정률 리스트 반환.
    region 값이 '전국,경기' 처럼 복합값일 수 있으므로 LIKE 매칭 사용.
    예: region='경기' → '경기', '전국,경기', '인천,경기' 모두 포함.
    before_date가 있으면 해당 날짜 이전 데이터만 조회 (백테스트용).
    """
    conditions = [
        BidsHistory.region.like(f"%{region}%"),
        BidLicenseType.type_name == project_type,
        _bucket_filter(bucket_id),
        _bid_type_filter(bid_type),
    ]
    if before_date is not None:
        conditions.append(BidsHistory.bid_date < before_date)

    result = await db.execute(
        select(BidsHistory.adjustment_rate)
        .join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
        .where(*conditions)
    )
    return [row[0] for row in result.fetchall()]


async def get_rates_by_type_and_bucket(
    db: AsyncSession,
    project_type: str,
    bucket_id: int,
    bid_type: str = TARGET_BID_TYPE,
    before_date: date | None = None,
) -> list[Decimal]:
    """공종 + 버킷 기준 사정률 리스트 반환.
    before_date가 있으면 해당 날짜 이전 데이터만 조회 (백테스트용).
    """
    conditions = [
        BidLicenseType.type_name == project_type,
        _bucket_filter(bucket_id),
        _bid_type_filter(bid_type),
    ]
    if before_date is not None:
        conditions.append(BidsHistory.bid_date < before_date)

    result = await db.execute(
        select(BidsHistory.adjustment_rate)
        .join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
        .where(*conditions)
    )
    return [row[0] for row in result.fetchall()]


async def get_all_rates(
    db: AsyncSession,
    project_type: str,
    bid_type: str = TARGET_BID_TYPE,
    before_date: date | None = None,
) -> list[Decimal]:
    """공종 전체 사정률 리스트 반환 (최후 Fallback, 버킷 구분 없음).
    before_date가 있으면 해당 날짜 이전 데이터만 조회 (백테스트용).
    """
    conditions = [
        BidLicenseType.type_name == project_type,
        _bid_type_filter(bid_type),
    ]
    if before_date is not None:
        conditions.append(BidsHistory.bid_date < before_date)

    result = await db.execute(
        select(BidsHistory.adjustment_rate)
        .join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
        .where(*conditions)
    )
    return [row[0] for row in result.fetchall()]
