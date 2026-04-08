"""
app/data/fallback.py
계층형 Fallback 로직.

발주처 → 지역 → 공종+버킷 → 전체 순으로 사정률 데이터를 조회한다.
각 레벨은 MIN_SAMPLE_SIZE(20건) 이상일 때만 채택한다.

모든 쿼리는 bid_type='적격심사' 필터가 기본 적용된다.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    MIN_SAMPLE_SIZE,
    TARGET_BID_TYPE,
    get_all_rates,
    get_rates_by_client,
    get_rates_by_region,
    get_rates_by_type_and_bucket,
)

# Fallback 레벨 명칭 (Response의 fallback_level 필드에 사용)
LEVEL_CLIENT  = "client"
LEVEL_REGION  = "region"
LEVEL_BUCKET  = "type_bucket"
LEVEL_GLOBAL  = "global"
LEVEL_NONE    = "none"   # 데이터 없음


async def get_rates_with_fallback(
    db: AsyncSession,
    client_name: str,
    region: str,
    project_type: str,
    bucket_id: int,
    bid_type: str = TARGET_BID_TYPE,
    client_id: str | None = None,
    before_date: date | None = None,
) -> tuple[list[Decimal], str]:
    """
    Fallback 우선순위에 따라 사정률 리스트와 사용된 레벨을 반환한다.

    우선순위:
        1. 발주처 (client)         - sample_size >= 20
        2. 지역 (region)           - sample_size >= 20
        3. 공종+버킷 (type_bucket) - sample_size >= 20
        4. 전체 (global)           - sample_size >= 20
        5. none                    - 데이터 부족

    Args:
        db: 비동기 DB 세션
        client_name: 발주처명
        region: 정규화된 지역 (예: "서울", "경기")
        project_type: 정규화된 공종 (예: "실내건축", "조경")
        bucket_id: 금액 버킷 ID
        bid_type: 입찰방식 필터 (기본: "적격심사")
        client_id: 발주청 코드 (있으면 이름보다 우선)
        before_date: 이 날짜 이전 데이터만 조회 (None이면 전체)

    Returns:
        (rates, fallback_level) 튜플
    """

    # 1. 발주처
    rates = await get_rates_by_client(
        db, client_name, project_type, bucket_id, bid_type, client_id,
        before_date=before_date,
    )
    if len(rates) >= MIN_SAMPLE_SIZE:
        return rates, LEVEL_CLIENT

    # 2. 지역
    rates = await get_rates_by_region(
        db, region, project_type, bucket_id, bid_type,
        before_date=before_date,
    )
    if len(rates) >= MIN_SAMPLE_SIZE:
        return rates, LEVEL_REGION

    # 3. 공종 + 버킷
    rates = await get_rates_by_type_and_bucket(
        db, project_type, bucket_id, bid_type,
        before_date=before_date,
    )
    if len(rates) >= MIN_SAMPLE_SIZE:
        return rates, LEVEL_BUCKET

    # 4. 전체 (최후 수단)
    rates = await get_all_rates(
        db, project_type, bid_type,
        before_date=before_date,
    )
    if len(rates) >= MIN_SAMPLE_SIZE:
        return rates, LEVEL_GLOBAL

    return [], LEVEL_NONE
