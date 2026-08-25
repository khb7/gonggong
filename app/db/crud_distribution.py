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

# 공고별 분포 채택 최소 참여자 행 수.
# 이 미만이면 다음 fallback 레벨로 내려간다.
_MIN_DIST_SAMPLE = 200

# Fallback 레벨 명칭 (Response의 fallback_level 필드에 사용)
LEVEL_CLIENT = "client"
LEVEL_REGION = "region"
LEVEL_BUCKET = "type_bucket"
LEVEL_GLOBAL = "global"

# bid_type/price_method 완화 필터.
# Info21c CSV에는 예정가격결정방식 컬럼이 없어 대부분 '기타'로 적재된다.
# (현재 DB: price_method '기타' 97% / '복수예비가격' 3%)
# 따라서 '복수예비가격'만 거르면 데이터가 붕괴하므로 '기타'를 함께 허용한다.
_RELAX_FILTERS = (
    or_(BidsHistory.bid_type == TARGET_BID_TYPE, BidsHistory.bid_type == "기타"),
    or_(BidsHistory.price_method == TARGET_PRICE_METHOD, BidsHistory.price_method == "기타"),
)

# bid_rate 로 인정하는 범위.
# 투찰률은 기초금액 대비 비율이라 1 을 크게 넘거나 음수일 수 없다. 그런데 원본에는
#   - bid_amount 가 99999999999999 인 더미 행 (무효/미제출) → bid_rate 45만
#   - rank 가 음수로 파싱된 깨진 행                        → bid_rate -9
# 이 섞여 있고, 걸러내지 않으면 offset_pct 가 -1033% ~ +1729% 로 폭주해
# 히스토그램 구간이 2,700 개까지 늘어난다.
# 하한은 0 이 아니라 0.5 다. 낙찰하한율이 아무리 낮아도 0.6 대이므로
# bid_rate 0.03 같은 값은 금액 자리수가 깨진 행이고, 남겨 두면 offset 하한이
# -84% 까지 늘어져 히스토그램 축이 못 쓰게 된다.
_RATE_MIN = Decimal("0.5")
_RATE_MAX = Decimal("1.05")

_RATE_SANITY_FILTERS = (
    BidParticipants.bid_rate >= _RATE_MIN,
    BidParticipants.bid_rate <= _RATE_MAX,
)


def _is_usable_client_id(client_id: str | None) -> bool:
    """client_id 를 필터로 쓸 수 있는지.

    수집 경로가 client_id 를 채우지 못해 실 DB 는 전 행이 문자열 'None' 이다.
    truthy 라서 그대로 두면 `client_id == 'None'` 이 참이 되어 모든 발주처가
    한 덩어리로 매칭되고, client 레벨이 사실상 global 이 된다.
    """
    return bool(client_id) and client_id != "None"


async def _fetch_offset_rows(
    db: AsyncSession,
    conditions: list,
    join_license: bool,
) -> list[dict]:
    """주어진 조건으로 participant offset 행을 조회한다."""
    q = (
        select(
            BidParticipants.bid_rate,
            BidsHistory.lower_limit_rate,
            BidParticipants.is_winner,
        )
        .join(BidsHistory, BidParticipants.project_id == BidsHistory.project_id)
    )
    if join_license:
        q = q.join(
            BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id
        )
    q = q.where(*_RELAX_FILTERS, *_RATE_SANITY_FILTERS, *conditions)
    result = await db.execute(q)
    return [
        {"bid_rate": row.bid_rate, "lower_limit_rate": row.lower_limit_rate, "is_winner": row.is_winner}
        for row in result.fetchall()
    ]


async def get_offset_distribution(
    db: AsyncSession,
    client_name: str = "",
    region: str = "",
    project_type: str = "",
    bucket_id: int = 1,
    client_id: str | None = None,
) -> tuple[list[dict], str]:
    """
    공고 peer group에 맞는 participant offset 행을 계층형 fallback으로 조회한다.

    우선순위 (각 레벨 _MIN_DIST_SAMPLE 이상일 때 채택):
        1. 발주처 + 공종 + 버킷 (client)
        2. 지역 + 공종 + 버킷 (region)
        3. 공종 + 버킷 (type_bucket)
        4. 전체 (global) — 무조건 반환 (최후 수단)

    Returns:
        (rows, fallback_level) 튜플.
        rows: [{"bid_rate": Decimal, "lower_limit_rate": Decimal, "is_winner": bool}, ...]
    """
    # 1. 발주처 + 공종 + 버킷
    if (_is_usable_client_id(client_id) or client_name) and project_type:
        client_filter = (
            BidsHistory.client_id == client_id
            if _is_usable_client_id(client_id)
            else BidsHistory.client_name == client_name
        )
        rows = await _fetch_offset_rows(
            db,
            [client_filter, BidLicenseType.type_name == project_type, _bucket_filter(bucket_id)],
            join_license=True,
        )
        if len(rows) >= _MIN_DIST_SAMPLE:
            return rows, LEVEL_CLIENT

    # 2. 지역 + 공종 + 버킷
    if region and project_type:
        rows = await _fetch_offset_rows(
            db,
            [
                or_(BidsHistory.region.like(f"%{region}%"), BidsHistory.region == "전국"),
                BidLicenseType.type_name == project_type,
                _bucket_filter(bucket_id),
            ],
            join_license=True,
        )
        if len(rows) >= _MIN_DIST_SAMPLE:
            return rows, LEVEL_REGION

    # 3. 공종 + 버킷
    if project_type:
        rows = await _fetch_offset_rows(
            db,
            [BidLicenseType.type_name == project_type, _bucket_filter(bucket_id)],
            join_license=True,
        )
        if len(rows) >= _MIN_DIST_SAMPLE:
            return rows, LEVEL_BUCKET

    # 4. 전체 (최후 수단 — 무조건 반환)
    rows = await _fetch_offset_rows(db, [], join_license=False)
    return rows, LEVEL_GLOBAL


async def get_offset_distribution_cached(
    db: AsyncSession,
    client_name: str = "",
    region: str = "",
    project_type: str = "",
    bucket_id: int = 1,
    client_id: str | None = None,
) -> tuple[list[dict], str]:
    """캐시된 offset distribution을 반환한다. 캐시 미스 시 DB를 쿼리하고 캐시에 저장한다."""
    cache_key = f"dist:{client_id or client_name}:{region}:{project_type}:{bucket_id}"
    cached = distribution_cache.get(cache_key)
    if cached is not None:
        return cached
    result = await get_offset_distribution(
        db, client_name, region, project_type, bucket_id, client_id
    )
    distribution_cache.set(cache_key, result)
    return result


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
    async def _avg(conditions, join_license: bool = False) -> int | None:
        # 공종 조건을 쓰는 레벨에서만 join 한다. 공고 하나에 공종이 여러 개
        # 붙어 있어(실 DB 최대 14 개), 불필요한 join 은 그 수만큼 공고를
        # 중복 계산해 평균을 부풀린다.
        q = select(
            func.avg(BidsHistory.participants).label("avg_p"), func.count().label("cnt")
        )
        if join_license:
            q = q.join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
        q = q.where(*conditions)
        row = (await db.execute(q)).one()
        if row.cnt >= _MIN_SAMPLE and row.avg_p is not None:
            return int(row.avg_p)
        return None

    # 분포 쿼리와 같은 완화 필터를 쓴다. 여기만 strict 로 두면 실 DB 의 97% 를
    # 차지하는 price_method='기타' 공고가 통째로 빠져 표본이 붕괴하고,
    # 참여자 수가 실제의 1/10 로 떨어진다.
    base = list(_RELAX_FILTERS)

    # 1. 발주처
    result = await _avg([*base, BidsHistory.client_name == client_name])
    if result is not None:
        return result

    # 2. 지역
    result = await _avg([*base, or_(BidsHistory.region.like(f"%{region}%"), BidsHistory.region == "전국")])
    if result is not None:
        return result

    # 3. 공종 + 버킷
    result = await _avg(
        [*base, BidLicenseType.type_name == project_type, _bucket_filter(bucket_id)],
        join_license=True,
    )
    if result is not None:
        return result

    # 4. 전체
    result = await _avg(base)
    return result or 0
