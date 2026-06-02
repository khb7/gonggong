"""
app/api/v1/distribution.py
POST /api/v1/bid/distribution 엔드포인트
"""

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.db.normalize import normalize_region, normalize_project_type
from app.db.models import ProjectBucket
from app.db.crud_distribution import get_offset_distribution_cached, get_avg_participants
from app.engine.distribution import build_offset_distribution, calc_my_position
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
            lower_limit_rate=Decimal("0.87745"),
            participants=0,
        )

    # ── 2. Override 적용 ─────────────────────────────────────
    base_price = notice.base_price
    lower_limit_rate = notice.lower_limit_rate
    client_name = notice.client_name
    region = normalize_region(notice.region)
    project_type = normalize_project_type(notice.project_type) or notice.project_type

    if body.overrides:
        if body.overrides.base_price is not None:
            base_price = body.overrides.base_price
        if body.overrides.lower_limit_rate is not None:
            lower_limit_rate = body.overrides.lower_limit_rate
        if body.overrides.client_name is not None:
            client_name = body.overrides.client_name
        if body.overrides.region is not None:
            region = normalize_region(body.overrides.region)
        if body.overrides.project_type is not None:
            project_type = normalize_project_type(body.overrides.project_type) or body.overrides.project_type

    bucket_id = ProjectBucket.get_bucket_id(base_price) if base_price > 0 else 1

    # ── 3. 분포 조회 ─────────────────────────────────────────
    rows = await get_offset_distribution_cached(db)
    distribution = build_offset_distribution(rows)
    total_bids = sum(b["count"] for b in distribution)

    # ── 4. 참여자 수 예측 ─────────────────────────────────────
    estimated_participants = await get_avg_participants(
        db, client_name, region, project_type, bucket_id
    )

    # ── 5. 내 위치 계산 ───────────────────────────────────────
    my_position_out: MyPositionResponse | None = None
    if body.my_bid_price and base_price > 0:
        pos = calc_my_position(body.my_bid_price, base_price, lower_limit_rate, distribution)
        if pos:
            my_position_out = MyPositionResponse(**pos)

    # ── 6. 분포 응답 변환 ─────────────────────────────────────
    distribution_out = [
        OffsetBucketResponse(
            offset_pct=b["offset_pct"],
            count=b["count"],
            win_count=b["win_count"],
            historical_win_rate=round(b["win_count"] / b["count"] * 100, 2) if b["count"] > 0 else None,
        )
        for b in distribution
    ]

    return DistributionResponse(
        bid_notice_id=body.bid_notice_id,
        base_price=base_price,
        lower_limit_rate=float(lower_limit_rate),
        estimated_participants=estimated_participants,
        g2b_fetch_status=g2b_status,
        distribution=distribution_out,
        data_quality=DataQuality(total_bids=total_bids),
        my_position=my_position_out,
    )
