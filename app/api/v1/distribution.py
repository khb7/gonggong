"""
app/api/v1/distribution.py
POST /api/v1/bid/distribution 엔드포인트
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.db.normalize import normalize_region, normalize_project_type
from app.db.models import ProjectBucket
from app.db.crud_distribution import (
    get_offset_distribution_cached,
    resolve_offset_distribution,
    get_avg_participants,
    get_adjustment_rate_sigma,
)
from app.engine.distribution import build_scoped_distribution, calc_my_position
from app.schemas.distribution import (
    DistributionRequest,
    DistributionResponse,
    OffsetBucketResponse,
    MyPositionResponse,
    DataQuality,
)

router = APIRouter()


def _get_fetcher():
    from app.external.g2b_fetcher import G2BFetcher, MockG2BFetcher
    if settings.use_mock_g2b:
        return MockG2BFetcher()
    return G2BFetcher(api_key=settings.G2B_API_KEY)


@router.post("/bid/distribution", response_model=DistributionResponse)
async def get_bid_distribution(
    body: DistributionRequest,
    db: AsyncSession = Depends(get_db),
) -> DistributionResponse:
    """
    경쟁자 분포 조회 엔드포인트.

    과거 참여자 offset 분포와 내 투찰가 위치를 반환한다.
    my_bid_price 없으면 my_position은 null.
    """

    # ── 1. G2B 공고 조회 ─────────────────────────────────────
    fetcher = _get_fetcher()
    g2b_status = "mock" if settings.use_mock_g2b else "ok"
    try:
        notice = await fetcher.fetch(body.bid_notice_id)
    except Exception:
        g2b_status = "failed"
        from app.external.g2b_fetcher import G2BNoticeData
        notice = G2BNoticeData(
            base_price=0,
            client_name="",
            region="",
            project_type="",
            lower_limit_rate=None,
            participants=0,
        )

    # ── 2. Override 적용 ─────────────────────────────────────
    base_price = notice.base_price
    lower_limit_rate = notice.lower_limit_rate
    # A값은 G2B 개방표준 API에 항목이 없다 → override로만 들어온다.
    a_value = 0
    client_name = notice.client_name
    region = normalize_region(notice.region)
    project_type = normalize_project_type(notice.project_type) or notice.project_type

    if body.overrides:
        if body.overrides.base_price is not None:
            base_price = body.overrides.base_price
        if body.overrides.lower_limit_rate is not None:
            lower_limit_rate = body.overrides.lower_limit_rate
        if body.overrides.a_value is not None:
            a_value = body.overrides.a_value
        if body.overrides.client_name is not None:
            client_name = body.overrides.client_name
        if body.overrides.region is not None:
            region = normalize_region(body.overrides.region)
        if body.overrides.project_type is not None:
            project_type = normalize_project_type(body.overrides.project_type) or body.overrides.project_type

    # offset 축 전체가 낙찰하한율 기준선 위에서 정의된다.
    # 값을 모르면 분포도 내 위치도 의미가 없으므로 추측하지 않고 입력을 요구한다.
    if lower_limit_rate is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "낙찰하한율을 자동 조회할 수 없습니다. "
                "공고문의 낙찰하한율을 확인해 '낙찰하한율' 필드에 입력 후 다시 조회하세요. "
                "(2025-07-08 지방계약 / 2026-01-30 국가계약 개정으로 구간별 하한율이 2%p 상향되었습니다)"
            ),
        )

    bucket_id = ProjectBucket.get_bucket_id(base_price) if base_price > 0 else 1

    # ── 3. 분포 조회 (발주처 → 지역 → 공종+버킷 → 전체) ──────
    rows, scope = await resolve_offset_distribution(
        db, client_name, region, project_type, bucket_id
    )

    # 낙찰 빈도는 항상 전체 표본에서 계산한다 (build_scoped_distribution 주석 참고).
    global_rows = None if scope.level == "global" else await get_offset_distribution_cached(db)
    distribution = build_scoped_distribution(rows, global_rows)

    total_bids = sum(b["count"] for b in distribution)
    win_rate_bids = len(global_rows) if global_rows is not None else len(rows)

    # ── 4. 참여자 수 예측 ─────────────────────────────────────
    # 참여자 평균은 부가 정보다. 여기서 실패해도 분포 응답까지 죽이지 않는다.
    try:
        estimated_participants = await get_avg_participants(
            db, client_name, region, project_type, bucket_id
        )
    except Exception:
        estimated_participants = 0

    # ── 5. 내 위치 계산 ───────────────────────────────────────
    #
    # 내 위치는 사정률≈1.0 근사로 잰 점 추정이라 실제와 어긋난다.
    # (히스토그램의 과거 offset 은 확정된 예정가격 기준, 내 위치는 기초금액 기준)
    # σ 를 구해 넘기면 그 어긋남을 ±1σ 밴드로 함께 반환한다.
    # 여기서 실패해도 분포 응답까지 죽이지 않는다 — 밴드만 사라진다.
    try:
        rate_sigma = await get_adjustment_rate_sigma(db)
    except Exception:
        rate_sigma = None

    my_position_out: MyPositionResponse | None = None
    if body.my_bid_price and base_price > 0:
        pos = calc_my_position(
            body.my_bid_price,
            base_price,
            lower_limit_rate,
            distribution,
            a_value,
            rate_sigma,
        )
        if pos:
            my_position_out = MyPositionResponse(**pos)

    # ── 6. 분포 응답 변환 ─────────────────────────────────────
    distribution_out = [
        OffsetBucketResponse(
            offset_pct=b["offset_pct"],
            count=b["count"],
            win_count=b["win_count"],
            historical_win_rate=b["historical_win_rate"],
        )
        for b in distribution
    ]

    return DistributionResponse(
        bid_notice_id=body.bid_notice_id,
        base_price=base_price,
        lower_limit_rate=float(lower_limit_rate),
        a_value=a_value,
        estimated_participants=estimated_participants,
        g2b_fetch_status=g2b_status,
        rate_sigma=float(rate_sigma) if rate_sigma else None,
        distribution=distribution_out,
        data_quality=DataQuality(
            total_bids=total_bids,
            distribution_level=scope.level,
            distribution_label=scope.label,
            sample_notices=scope.notices,
            win_rate_level="global",
            win_rate_bids=win_rate_bids,
        ),
        my_position=my_position_out,
    )
