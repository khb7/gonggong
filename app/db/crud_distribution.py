"""
app/db/crud_distribution.py
distribution engine용 DB 조회.
"""

from decimal import Decimal

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BidParticipants, BidsHistory, BidLicenseType
from app.db.crud import TARGET_BID_TYPE, TARGET_PRICE_METHOD, _bucket_filter
from app.engine import distribution_cache

_MIN_SAMPLE = 10
_DIST_CACHE_KEY = "offset_distribution"


async def get_offset_distribution(db: AsyncSession) -> list[dict]:
    """
    bid_participants JOIN bids_history 에서 offset 계산에 필요한 행을 반환한다.

    필터: 적격심사 + 복수예비가격

    Returns:
        [{"bid_rate": Decimal, "lower_limit_rate": Decimal, "is_winner": bool}, ...]
    """
    result = await db.execute(
        select(
            BidParticipants.bid_rate,
            BidsHistory.lower_limit_rate,
            BidParticipants.is_winner,
        )
        .join(BidsHistory, BidParticipants.project_id == BidsHistory.project_id)
        .where(
            BidsHistory.bid_type == TARGET_BID_TYPE,
            BidsHistory.price_method == TARGET_PRICE_METHOD,
        )
    )
    return [
        {"bid_rate": row.bid_rate, "lower_limit_rate": row.lower_limit_rate, "is_winner": row.is_winner}
        for row in result.fetchall()
    ]


async def get_offset_distribution_cached(db: AsyncSession) -> list[dict]:
    """캐시된 offset distribution을 반환한다. 캐시 미스 시 DB를 쿼리하고 캐시에 저장한다."""
    cached = distribution_cache.get(_DIST_CACHE_KEY)
    if cached is not None:
        return cached
    rows = await get_offset_distribution(db)
    distribution_cache.set(_DIST_CACHE_KEY, rows)
    return rows


async def get_avg_participants(
    db: AsyncSession,
    client_name: str,
    region: str,
    project_type: str,
    bucket_id: int,
) -> int:
    """
    유사 공고들의 평균 참여자 수를 반환한다.
    Fallback: 발주처 → 지역 → 공종+버킷 → 전체 (각 10건 이상)

    Returns:
        평균 참여자 수 (0이면 데이터 없음)
    """
    async def _avg(conditions) -> int | None:
        q = (
            select(func.avg(BidsHistory.participants).label("avg_p"), func.count().label("cnt"))
            .join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
            .where(*conditions)
        )
        row = (await db.execute(q)).one()
        if row.cnt >= _MIN_SAMPLE and row.avg_p is not None:
            return int(row.avg_p)
        return None

    base = [
        BidsHistory.bid_type == TARGET_BID_TYPE,
        BidsHistory.price_method == TARGET_PRICE_METHOD,
    ]

    # 1. 발주처
    result = await _avg([*base, BidsHistory.client_name == client_name])
    if result is not None:
        return result

    # 2. 지역
    result = await _avg([*base, or_(BidsHistory.region.like(f"%{region}%"), BidsHistory.region == "전국")])
    if result is not None:
        return result

    # 3. 공종 + 버킷
    result = await _avg([*base, BidLicenseType.type_name == project_type, _bucket_filter(bucket_id)])
    if result is not None:
        return result

    # 4. 전체
    result = await _avg(base)
    return result or 0
