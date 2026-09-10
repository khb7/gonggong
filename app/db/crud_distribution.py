"""
app/db/crud_distribution.py
distribution engine용 DB 조회.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, func, or_, exists, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    BidParticipants,
    BidsHistory,
    BidLicenseType,
    OffsetHistogram,
    OffsetScopeStat,
)
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

# ── 사정률 σ (내 위치 오차 밴드용) ────────────────────────────────────────
#
# 히스토그램 x축의 과거 offset 은 개찰로 확정된 **예정가격** 기준이고,
# 아직 개찰 전인 내 투찰가는 **기초금액** 기준으로 잰다 (사정률≈1.0 근사).
# 두 자가 다르므로 내 위치는 사정률이 흔들리는 만큼 좌우로 밀린다.
# 그 흔들림 폭을 재기 위한 값이 여기서 구하는 σ 다.
#
# 발주기관 유형별로 예비가격 생성 구간이 다르지만(조달청 ±2% / 지자체 ±3%),
# 사정률은 그중 4개의 **평균**이라 구간 차이가 거의 흡수된다.
# 실측 18,409건: 조달청 σ=0.0070 / 지자체 σ=0.0075 / 전체 σ=0.0072.
# 차이가 σ 자체의 5% 수준이라 기관별로 나누지 않고 전체 표본으로 계산한다.

_SIGMA_CACHE_KEY = "adjustment_rate_sigma"

# σ 계산에 요구하는 최소 표본 수
_MIN_SIGMA_SAMPLE = 100

# 사정률 유효 범위. 복수예비가격은 기초금액 ±3% 안에서 생성되므로 이 밖의 값은
# 적재 오염이다 (실측 min 0.950 / max 1.048). 오염분이 σ 를 부풀리는 것을 막는다.
_SIGMA_RATE_MIN = Decimal("0.90")
_SIGMA_RATE_MAX = Decimal("1.10")

# σ 상한. 이보다 크면 표본을 믿을 수 없다고 보고 밴드를 그리지 않는다.
_SIGMA_MAX = Decimal("0.05")


@dataclass(frozen=True)
class DistributionScope:
    """분포 계산에 실제로 사용된 fallback 레벨."""

    level: str          # "client" | "region" | "global"
    label: str | None   # 해당 레벨의 필터값 (global이면 None)
    notices: int        # 이 레벨의 공고 수
    bids: int           # 이 레벨의 참여자 행 수


# 낙찰자 투찰율이 법정 하한율보다 낮게 계산되는 공고를 걸러내기 위한 허용 오차.
# 낙찰하한가는 원 단위 절사되므로 미세하게 밑돌 수 있다.
_INVARIANT_TOLERANCE = Decimal("0.00002")


def _trusted_limits_filter():
    """법정 하한율을 신뢰할 수 있는 공고만 남긴다.

    낙찰자의 투찰율이 법정 하한율보다 낮은 건 물리적으로 불가능하다
    (하한 미달은 실격이라 낙찰자가 될 수 없다). 그런 공고는 legal_limit_rate
    가 틀린 것이고, **offset 좌표계 자체가 밀려 있으므로** 히스토그램에
    넣으면 안 된다.

    실측(12,445 공고 중 위반 261건 = 2.1%)을 제외했을 때:

        낙찰자 offset 음수 비율   A값 0.3% → 0.0%   비A값 18.0% → 0.0%
        A값/비A값 분포 KS 거리    D=0.149 → D=0.079

    비A값 공고의 꼬리가 p5=-8.0 / p95=+8.2 로 벌어져 있던 것이 이 2.1% 때문이다.
    A값 유무로 히스토그램을 가를 필요는 없다 — bid_rate 가 이미 A값 조정값이라
    두 그룹은 같은 축 위에 있다(A값 크기와 낙찰자 offset 사이에 단조 관계 없음).
    """
    return ~exists(
        select(1)
        .select_from(BidParticipants)
        .where(
            BidParticipants.project_id == BidsHistory.project_id,
            BidParticipants.is_winner.is_(True),
            BidParticipants.bid_rate
            < func.coalesce(BidsHistory.legal_limit_rate, BidsHistory.lower_limit_rate)
            - _INVARIANT_TOLERANCE,
        )
        .correlate(BidsHistory)
    )


def _verifiable_limits_filter():
    """낙찰하한율을 **대조할 수 있는** 공고만 남긴다.

    `_trusted_limits_filter()` 는 "모순이 드러난" 공고를 뺀다. 이 필터는 한 겹
    앞이다 — 애초에 모순이 드러날 수 없는 공고를 뺀다.

    낙찰하한가가 있어야 `낙찰하한가 / 예정가격` 으로 법정 하한율을 검산할 수
    있다. 없으면 `split_limit_rates()` 가 원본 신고값을 법정=실효 양쪽에 그대로
    넣고 끝나서(`if not lower_limit_price` 분기), 그 값이 틀려도 알 방법이 없다.

    실측이 그 차이를 보여준다 — 낙찰자 불변식 위반율:

        낙찰하한가 있음   15,430 공고 중 174 (1.1%)
        낙찰하한가 없음      877 공고 중 229 (26.1%)   ← 23배

    26% 가 깨진 모집단은 나머지 74% 도 믿을 근거가 없다. offset 기준선이
    법정 하한율이므로 기준선을 못 믿으면 그 공고의 좌표계 전체가 의미를 잃는다.
    행은 보존하되 집계에서만 뺀다 (전체 16,307 공고 중 877 = 5.4%).
    """
    return BidsHistory.lower_limit_price > 0


def _target_filters() -> list:
    """
    통계 대상 필터 (적격심사 + 복수예비가격 + 하한율 신뢰 가능).

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
        _verifiable_limits_filter(),
        _trusted_limits_filter(),
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

# offset bin 해상도. app/engine/distribution.py::_BIN_PCT_RESOLUTION 과 반드시 같아야 한다
# — SQL 집계 결과와 파이썬 집계 결과가 같은 bin 에 떨어져야 하기 때문이다.
_BIN_DECIMALS = 1

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


def scope_key_for(level: str, label: str | None) -> str:
    """사전계산 표의 scope_key 를 만든다.

    빌더(scripts/build_offset_histogram.py)와 조회가 **같은 함수**를 써야 한다.
    양쪽이 다른 규칙으로 키를 만들면 표는 채워져 있는데 조회가 못 찾고,
    조용히 느린 실시간 경로로 떨어진다 — 증상이 "가끔 느림" 이라 잡기 어렵다.
    """
    return label or ""


async def get_precomputed_distribution(
    db: AsyncSession, level: str, key: str
) -> list[dict] | None:
    """사전계산된 히스토그램. 없으면 None."""
    rows = (
        await db.execute(
            select(
                OffsetHistogram.offset_pct,
                OffsetHistogram.count,
                OffsetHistogram.win_count,
            )
            .where(
                OffsetHistogram.scope_level == level,
                OffsetHistogram.scope_key == key,
            )
            .order_by(OffsetHistogram.offset_pct)
        )
    ).fetchall()
    if not rows:
        return None
    return [
        {"offset_pct": float(r.offset_pct), "count": int(r.count), "win_count": int(r.win_count)}
        for r in rows
    ]


async def get_precomputed_scope_stat(
    db: AsyncSession, level: str, key: str
) -> tuple[int, int] | None:
    """사전계산된 (공고 수, 참여자 수). 없으면 None."""
    row = (
        await db.execute(
            select(OffsetScopeStat.notices, OffsetScopeStat.bids).where(
                OffsetScopeStat.scope_level == level,
                OffsetScopeStat.scope_key == key,
            )
        )
    ).first()
    return (int(row.notices), int(row.bids)) if row else None


async def get_offset_distribution(
    db: AsyncSession,
    *,
    client_name: str | None = None,
    region: str | None = None,
    project_type: str | None = None,
    bucket_id: int | None = None,
) -> list[dict]:
    """
    offset 히스토그램을 **SQL 에서 집계해** 반환한다.

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
        offset_pct 오름차순 bin 목록.
        [{"offset_pct": float, "count": int, "win_count": int}, ...]
    """
    conditions, needs_license = _scope_conditions(client_name, region, project_type, bucket_id)

    # ⚠ 집계는 반드시 SQL 에서 한다.
    #
    # 예전에는 참여자 행을 그대로 반환하고 파이썬이 셌다. 글로벌 스코프는
    # 4,490,350 행이라 RAM 1GB 서버(E2.1.Micro)에서 스래싱으로 OS 가 멈췄다.
    # SQL 집계로 바꾸면 결과가 579 bin 이고 RSS 14.6MB 다 (서버 실측).
    offset_pct = func.round(
        (
            BidParticipants.bid_rate
            - func.coalesce(BidsHistory.legal_limit_rate, BidsHistory.lower_limit_rate)
        )
        * 100,
        _BIN_DECIMALS,
    ).label("offset_pct")

    q = (
        select(
            offset_pct,
            func.count().label("count"),
            func.sum(
                case((BidParticipants.is_winner.is_(True), 1), else_=0)
            ).label("win_count"),
        )
        .select_from(BidParticipants)
        .join(BidsHistory, BidParticipants.project_id == BidsHistory.project_id)
    )
    if needs_license:
        q = q.join(BidLicenseType, BidsHistory.project_id == BidLicenseType.project_id)

    result = await db.execute(q.where(*conditions).group_by(offset_pct).order_by(offset_pct))
    return [
        {
            "offset_pct": float(row.offset_pct),
            "count": int(row.count),
            "win_count": int(row.win_count or 0),
        }
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

    # 사전계산 표 우선. 특히 글로벌은 실시간 스캔이 69초라(서버 실측)
    # 낙찰 빈도용으로 매 요청 부르는 이 경로가 그대로면 사용자가 못 쓴다.
    level = (
        "global" if not (client_name or region or project_type)
        else "region" if region and not client_name
        else "client"
    )
    if level != "client":
        label = None if level == "global" else region
        pre = await get_precomputed_distribution(
            db, level, scope_key_for(level, label)
        )
        if pre is not None:
            distribution_cache.set(key, pre)
            return pre

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
) -> tuple[list[dict], DistributionScope]:
    """
    계층형 fallback으로 분포 행과 사용된 레벨을 함께 반환한다.

    Fallback: 발주처 → 지역 → 전체.
    각 레벨은 공고 수가 _MIN_DIST_NOTICES 이상일 때만 채택된다.

    공종+버킷(type_bucket) 계층은 2026 홀드아웃 백테스트에서 밴드 적중률이
    74.8% 로 같은 공고의 global 76.7% 보다 낮아 제거했다. 공종·금액으로
    쪼개면 표본만 줄고 신호는 흐려진다.

    Returns:
        (rows, scope)
    """
    candidates: list[tuple[str, str | None, dict]] = []
    if client_name:
        candidates.append(("client", client_name, {"client_name": client_name}))
    if region:
        candidates.append(("region", region, {"region": region}))

    candidates.append((_GLOBAL_SCOPE_KEY, None, {}))

    for level, label, kwargs in candidates:
        skey = scope_key_for(level, label)

        # 사전계산 표를 먼저 본다. 넓은 스코프는 실시간 스캔이 수십 초라
        # (서버 실측 region 22.3s / global 69.1s) 이 경로가 사실상 필수다.
        stat = await get_precomputed_scope_stat(db, level, skey)
        if stat is not None:
            notices, bids = stat
            if level != _GLOBAL_SCOPE_KEY and notices < _MIN_DIST_NOTICES:
                continue
            bins = await get_precomputed_distribution(db, level, skey)
            if bins is not None:
                return bins, DistributionScope(
                    level=level, label=label, notices=notices, bids=bids
                )

        notices, bids = await count_offset_distribution(db, **kwargs)
        if level != _GLOBAL_SCOPE_KEY and notices < _MIN_DIST_NOTICES:
            continue
        bins = await get_offset_distribution_cached(
            db, **kwargs, _cache_key_override=_cache_key(level, label)
        )
        return bins, DistributionScope(level=level, label=label, notices=notices, bids=bids)

    # candidates 마지막이 글로벌이라 여기 도달하지 않는다. 방어적으로만 남긴다.
    bins = await get_offset_distribution_cached(db)
    notices, bids = await count_offset_distribution(db)
    return bins, DistributionScope(
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


async def get_adjustment_rate_sigma(db: AsyncSession) -> Decimal | None:
    """
    사정률의 표준편차 σ 를 반환한다. 내 위치 오차 밴드의 폭이 되는 값이다.

    표본이 부족하거나(_MIN_SIGMA_SAMPLE 미만) σ 가 비상식적으로 크면
    (_SIGMA_MAX 초과) None 을 반환한다. 이 경우 밴드를 그리지 않는다 —
    근거 없는 폭을 그리느니 안 그리는 편이 낫다.

    Returns:
        σ (Decimal, 소수 단위. 예: Decimal("0.0072")) 또는 None
    """
    cached = distribution_cache.get(_SIGMA_CACHE_KEY)
    if cached is not None:
        # None 결과도 캐시해야 매 요청마다 재조회하지 않는다 → 1-튜플로 감싼다.
        return cached[0]

    q = (
        select(
            func.stddev_samp(BidsHistory.adjustment_rate).label("sigma"),
            func.count().label("cnt"),
        )
        .select_from(BidsHistory)
        .where(
            *_target_filters(),
            BidsHistory.adjustment_rate >= _SIGMA_RATE_MIN,
            BidsHistory.adjustment_rate <= _SIGMA_RATE_MAX,
        )
    )
    row = (await db.execute(q)).one()

    sigma: Decimal | None = None
    if row.cnt is not None and row.cnt >= _MIN_SIGMA_SAMPLE and row.sigma is not None:
        candidate = Decimal(str(row.sigma))
        if Decimal(0) < candidate <= _SIGMA_MAX:
            sigma = candidate

    distribution_cache.set(_SIGMA_CACHE_KEY, (sigma,))
    return sigma
