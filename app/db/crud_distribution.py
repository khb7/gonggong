"""
app/db/crud_distribution.py
distribution engine용 DB 조회.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BidParticipants, BidsHistory, BidLicenseType
from app.db.crud import TARGET_BID_TYPE, TARGET_PRICE_METHOD, _bucket_filter
from app.engine import distribution_cache

# 참여자 평균(get_avg_participants) fallback 최소 건수
_MIN_SAMPLE = 10

# 분포 필터를 채택하기 위한 최소 "공고 수".
#
# 참여자 행 수가 아니라 공고 수를 기준으로 삼는다. 공공입찰은 공고 1건에
# 수백 명이 참여하므로 행 수로 재면 공고 1건만으로도 수백 행이 나와서,
# 그 한 건의 특수 상황이 "발주처 분포"로 둔갑한다.
_MIN_DIST_NOTICES = 10

# 전체(글로벌) 분포 캐시 키 — 하위 호환용으로 이름을 유지한다.
_DIST_CACHE_KEY = "offset_distribution"

_GLOBAL_SCOPE_KEY = "global"


@dataclass(frozen=True)
class DistributionScope:
    """분포 계산에 실제로 사용된 fallback 레벨."""

    level: str          # "client" | "region" | "type_bucket" | "global"
    label: str | None   # 해당 레벨의 필터값 (global이면 None)
    notices: int        # 이 레벨의 공고 수
    bids: int           # 이 레벨의 참여자 행 수


def _target_filters() -> list:
    """
    통계 대상 필터 (적격심사 + 복수예비가격).

    기존 적재분의 bid_type/price_method가 '기타'로 저장되어 있어 함께 허용한다.
    백필 완료 후 '기타' 허용을 제거할 것.
    """
    return [
        or_(
            BidsHistory.bid_type == TARGET_BID_TYPE,
            BidsHistory.bid_type == "기타",
        ),
        or_(
            BidsHistory.price_method == TARGET_PRICE_METHOD,
            BidsHistory.price_method == "기타",
        ),
    ]


# bid_rate 로 인정하는 범위.
#
# 투찰률은 기초금액 대비 비율이라 1 을 크게 넘거나 음수일 수 없다. 그런데 원본에는
#   - bid_amount 가 99999999999999 인 더미 행 (무효/미제출) → bid_rate 45만
#   - rank 가 음수로 파싱된 깨진 행                        → bid_rate -9
# 이 섞여 있고, 걸러내지 않으면 offset_pct 가 -1033% ~ +1729% 로 폭주해
# 히스토그램 구간이 2,700 개까지 늘어난다.
#
# 하한은 0 이 아니라 0.5 다. 낙찰하한율이 아무리 낮아도 0.6 대이므로
# bid_rate 0.03 같은 값은 금액 자리수가 깨진 행이고, 남겨 두면 offset 하한이
# -84% 까지 늘어져 히스토그램 축이 못 쓰게 된다.
_RATE_MIN = Decimal("0.5")
_RATE_MAX = Decimal("1.05")

_RATE_SANITY_FILTERS = (
    BidParticipants.bid_rate >= _RATE_MIN,
    BidParticipants.bid_rate <= _RATE_MAX,
)


def _region_filter(region: str):
    """지역 필터. region 컬럼은 '서울,경기'처럼 복수 값이 들어갈 수 있다."""
    return or_(BidsHistory.region.like(f"%{region}%"), BidsHistory.region == "전국")


def _scope_conditions(
    client_name: str | None,
    region: str | None,
    project_type: str | None,
    bucket_id: int | None,
) -> tuple[list, bool]:
    """
    필터 인자를 SQL 조건 목록과 '면허 테이블 조인 필요 여부'로 변환한다.
    """
    # 참여자 행을 보는 쿼리에만 붙인다. get_avg_participants 는 bid_participants 를
    # 조인하지 않으므로 _target_filters() 가 아니라 여기에 둔다.
    conditions = _target_filters() + list(_RATE_SANITY_FILTERS)
    if client_name:
        conditions.append(BidsHistory.client_name == client_name)
    if region:
        conditions.append(_region_filter(region))
    if bucket_id:
        conditions.append(_bucket_filter(bucket_id))
    needs_license = bool(project_type)
    if project_type:
        conditions.append(BidLicenseType.type_name == project_type)
    return conditions, needs_license


async def get_offset_distribution(
    db: AsyncSession,
    *,
    client_name: str | None = None,
    region: str | None = None,
    project_type: str | None = None,
    bucket_id: int | None = None,
) -> list[dict]:
    """
    bid_participants JOIN bids_history 에서 offset 계산에 필요한 행을 반환한다.

    필터: 적격심사 + 복수예비가격. 인자를 주면 해당 조건으로 좁힌다 (fallback 없음).

    offset 기준선은 **법정** 낙찰하한율이다.

    bid_participants.bid_rate(원본 `투찰율(%)`)는 이미 A값이 제거된
    조정 투찰율이기 때문이다:

        투찰율 = (투찰금액 − A) / (예정가격 − A)

    즉 투찰율은 법정 하한율과 같은 축 위에 있다. 실효 하한율
    (= 낙찰하한가/예정가격)로 재면 A값만큼 이중 차감되어 분포가 왼쪽으로 밀린다.
    실측: 낙찰자 불변식 위반이 법정 기준 0/223, 실효 기준 191/223.

    legal_limit_rate가 아직 없는 행은 lower_limit_rate로 폴백한다.
    근거: md/design/bid_rate_definitions.md

    Returns:
        [{"bid_rate": Decimal, "lower_limit_rate": Decimal, "is_winner": bool}, ...]
    """
    conditions, needs_license = _scope_conditions(client_name, region, project_type, bucket_id)

    q = (
        select(
            BidParticipants.bid_rate,
            func.coalesce(
                BidsHistory.legal_limit_rate, BidsHistory.lower_limit_rate
            ).label("lower_limit_rate"),
            BidParticipants.is_winner,
        )
        .join(BidsHistory, BidParticipants.project_id == BidsHistory.project_id)
    )
    if needs_license:
        q = q.join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)

    result = await db.execute(q.where(*conditions))
    return [
        {"bid_rate": row.bid_rate, "lower_limit_rate": row.lower_limit_rate, "is_winner": row.is_winner}
        for row in result.fetchall()
    ]


async def count_offset_distribution(
    db: AsyncSession,
    *,
    client_name: str | None = None,
    region: str | None = None,
    project_type: str | None = None,
    bucket_id: int | None = None,
) -> tuple[int, int]:
    """
    해당 필터의 (공고 수, 참여자 행 수)를 반환한다. 행을 전부 끌어오지 않고 세기만 한다.
    """
    conditions, needs_license = _scope_conditions(client_name, region, project_type, bucket_id)

    q = (
        select(
            func.count(func.distinct(BidsHistory.project_id)).label("notices"),
            func.count().label("bids"),
        )
        .select_from(BidParticipants)
        .join(BidsHistory, BidParticipants.project_id == BidsHistory.project_id)
    )
    if needs_license:
        q = q.join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)

    row = (await db.execute(q.where(*conditions))).one()
    return int(row.notices or 0), int(row.bids or 0)


def _cache_key(level: str, label: str | None, bucket_id: int | None = None) -> str:
    if level == "global":
        return _DIST_CACHE_KEY
    if level == "type_bucket":
        return f"offset_distribution:type:{label}:b{bucket_id}"
    return f"offset_distribution:{level}:{label}"


async def get_offset_distribution_cached(
    db: AsyncSession,
    *,
    client_name: str | None = None,
    region: str | None = None,
    project_type: str | None = None,
    bucket_id: int | None = None,
    _cache_key_override: str | None = None,
) -> list[dict]:
    """
    캐시된 offset distribution을 반환한다. 캐시 미스 시 DB를 쿼리하고 캐시에 저장한다.

    캐시 키는 필터 조합별로 분리된다. 인자가 없으면 전체(글로벌) 분포다.
    """
    key = _cache_key_override
    if key is None:
        if client_name:
            key = _cache_key("client", client_name)
        elif region:
            key = _cache_key("region", region)
        elif project_type:
            key = _cache_key("type_bucket", project_type, bucket_id)
        else:
            key = _DIST_CACHE_KEY

    cached = distribution_cache.get(key)
    if cached is not None:
        return cached
    rows = await get_offset_distribution(
        db,
        client_name=client_name,
        region=region,
        project_type=project_type,
        bucket_id=bucket_id,
    )
    distribution_cache.set(key, rows)
    return rows


async def resolve_offset_distribution(
    db: AsyncSession,
    client_name: str | None,
    region: str | None,
    project_type: str | None,
    bucket_id: int | None,
) -> tuple[list[dict], DistributionScope]:
    """
    계층형 fallback으로 분포 행과 사용된 레벨을 함께 반환한다.

    Fallback: 발주처 → 지역 → 공종+버킷 → 전체.
    각 레벨은 공고 수가 _MIN_DIST_NOTICES 이상일 때만 채택된다.

    Returns:
        (rows, scope)
    """
    candidates: list[tuple[str, str | None, dict]] = []
    if client_name:
        candidates.append(("client", client_name, {"client_name": client_name}))
    if region:
        candidates.append(("region", region, {"region": region}))
    if project_type:
        candidates.append((
            "type_bucket",
            project_type,
            {"project_type": project_type, "bucket_id": bucket_id},
        ))

    for level, label, kwargs in candidates:
        notices, bids = await count_offset_distribution(db, **kwargs)
        if notices < _MIN_DIST_NOTICES:
            continue
        rows = await get_offset_distribution_cached(
            db, **kwargs, _cache_key_override=_cache_key(level, label, bucket_id)
        )
        return rows, DistributionScope(level=level, label=label, notices=notices, bids=bids)

    rows = await get_offset_distribution_cached(db)
    notices, bids = await count_offset_distribution(db)
    return rows, DistributionScope(
        level=_GLOBAL_SCOPE_KEY, label=None, notices=notices, bids=bids
    )


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
        q = select(
            func.avg(BidsHistory.participants).label("avg_p"),
            func.count().label("cnt"),
        ).select_from(BidsHistory)
        if join_license:
            q = q.join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)
        row = (await db.execute(q.where(*conditions))).one()
        if row.cnt >= _MIN_SAMPLE and row.avg_p is not None:
            return int(row.avg_p)
        return None

    base = _target_filters()

    # 1. 발주처
    if client_name:
        result = await _avg([*base, BidsHistory.client_name == client_name])
        if result is not None:
            return result

    # 2. 지역
    if region:
        result = await _avg([*base, _region_filter(region)])
        if result is not None:
            return result

    # 3. 공종 + 버킷
    if project_type:
        result = await _avg(
            [*base, BidLicenseType.type_name == project_type, _bucket_filter(bucket_id)],
            join_license=True,
        )
        if result is not None:
            return result

    # 4. 전체
    result = await _avg(base)
    return result or 0
