"""
app/api/v1/bidding.py
POST /api/v1/bid/calculate 엔드포인트

Auto-Fetch Mode: bid_notice_id만 전달 → G2B에서 자동 파싱
Override Mode: overrides 필드로 특정 값 덮어쓰기
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.crud import TARGET_BID_TYPE
from app.db.session import get_db
from app.db.normalize import normalize_region, normalize_project_type, normalize_bid_type
from app.data.fallback import get_rates_with_fallback, LEVEL_NONE
from app.db.models import ProjectBucket
from app.engine.statistics import trimmed_median, mad, confidence_range
from app.engine.calculator import calculate_bid_spread
from app.schemas.request import BidRequest
from app.schemas.response import BidResponse, FetchedData

router = APIRouter()


def _get_fetcher():
    """API 키가 있으면 실제 G2BFetcher, 없으면 MockG2BFetcher를 반환한다."""
    from app.external.g2b_fetcher import G2BFetcher, MockG2BFetcher
    if settings.use_mock_g2b:
        return MockG2BFetcher()
    return G2BFetcher(api_key=settings.G2B_API_KEY)


@router.post("/bid/calculate", response_model=BidResponse)
async def calculate_bid(
    body: BidRequest,
    db: AsyncSession = Depends(get_db),
) -> BidResponse:
    """
    투찰가 계산 엔드포인트.

    - Auto-Fetch: bid_notice_id만 전달
    - Override: overrides 필드로 선택적 덮어쓰기

    Returns:
        3가지 전략(Aggressive / Normal / Safe)의 추천 투찰가 리스트
    """

    # ── 1. G2B 데이터 페치 ───────────────────────────────
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
            participants=100,
        )

    # base_price가 없으면 override 필수
    if notice.base_price == 0 and (
        body.overrides is None or body.overrides.base_price is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "기초금액을 자동 조회할 수 없습니다. "
                "G2B API는 단건 공고 조회를 지원하지 않아 직접 입력이 필요합니다. "
                "화면에서 '기초금액(원)' 필드에 값을 입력 후 다시 계산하세요."
            ),
        )

    # ── 2. Override 적용 ────────────────────────────────
    overridden_fields: list[str] = []
    mode = "auto"

    base_price = notice.base_price
    lower_limit_rate = notice.lower_limit_rate
    participants = notice.participants
    # A값은 G2B 개방표준 API에 항목이 없다 → override로만 들어온다.
    a_value = 0
    client_name = notice.client_name
    client_id = notice.client_id
    region = normalize_region(notice.region)
    project_type = normalize_project_type(notice.project_type) or notice.project_type
    # base_price=0 이면 G2B 공고 미확인 → bid_type도 신뢰 불가, 기본값 사용
    bid_type = notice.bid_type if notice.base_price > 0 else TARGET_BID_TYPE

    if body.overrides:
        mode = "override"
        if body.overrides.base_price is not None:
            base_price = body.overrides.base_price
            overridden_fields.append("base_price")
        if body.overrides.lower_limit_rate is not None:
            lower_limit_rate = body.overrides.lower_limit_rate
            overridden_fields.append("lower_limit_rate")
        if body.overrides.participants is not None:
            participants = body.overrides.participants
            overridden_fields.append("participants")
        if body.overrides.a_value is not None:
            a_value = body.overrides.a_value
            overridden_fields.append("a_value")
        if body.overrides.client_name is not None:
            client_name = body.overrides.client_name
            overridden_fields.append("client_name")
        if body.overrides.client_id is not None:
            client_id = body.overrides.client_id
            overridden_fields.append("client_id")
        if body.overrides.region is not None:
            region = normalize_region(body.overrides.region)
            overridden_fields.append("region")
        if body.overrides.project_type is not None:
            project_type = normalize_project_type(body.overrides.project_type) or body.overrides.project_type
            overridden_fields.append("project_type")
        if body.overrides.bid_type is not None:
            bid_type = normalize_bid_type(body.overrides.bid_type)
            overridden_fields.append("bid_type")

    # 낙찰하한율은 추측하지 않는다. 구간·계약법·개정시점마다 다른 값이라
    # 기본값을 쓰면 그럴듯하지만 틀린 투찰가가 나온다.
    if lower_limit_rate is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "낙찰하한율을 자동 조회할 수 없습니다. "
                "공고문의 낙찰하한율을 확인해 '낙찰하한율' 필드에 입력 후 다시 계산하세요. "
                "(2025-07-08 지방계약 / 2026-01-30 국가계약 개정으로 구간별 하한율이 2%p 상향되었습니다)"
            ),
        )

    # ── 3. 버킷 분류 ────────────────────────────────────
    bucket_id = ProjectBucket.get_bucket_id(base_price)

    # ── 4. Fallback 기반 사정률 데이터 조회 ──────────────
    try:
        rates, fallback_level = await get_rates_with_fallback(
            db=db,
            client_name=client_name,
            region=region,
            project_type=project_type,
            bucket_id=bucket_id,
            bid_type=bid_type,
            client_id=client_id,
        )
    except Exception as e:
        rates, fallback_level = [], LEVEL_NONE

    if fallback_level == LEVEL_NONE or not rates:
        # 데이터 부족 또는 DB 오류 시 기본 사정률 사용 (1.0000)
        predicted_rate = Decimal("1.0000")
        mad_val = Decimal("0.002")
        fallback_level = "default"
    else:
        # ── 5. 통계 계산 ────────────────────────────────
        predicted_rate = trimmed_median(rates)
        mad_val = mad(rates)

    # ── 5-1. 예측 구간 및 신뢰도 등급 계산 ──────────────
    rate_lower, rate_upper = confidence_range(predicted_rate, mad_val)
    if fallback_level == "default":
        confidence_grade = "low"
    elif mad_val <= Decimal("0.003"):
        confidence_grade = "high"
    elif mad_val <= Decimal("0.007"):
        confidence_grade = "medium"
    else:
        confidence_grade = "low"

    # ── 6. 투찰가 계산 (Multi-Shot Bid Spread) ──────────
    result = calculate_bid_spread(
        base_price=base_price,
        lower_limit_rate=lower_limit_rate,
        predicted_rate=predicted_rate,
        participants=participants,
        mad_val=mad_val,
        a_value=a_value,
    )

    # ── 7. 응답 구성 ────────────────────────────────────
    return BidResponse(
        bid_notice_id=body.bid_notice_id,
        mode=mode,
        overridden_fields=overridden_fields,
        g2b_fetch_status=g2b_status,
        fetched=FetchedData(
            base_price=notice.base_price,
            client_name=notice.client_name,
            region=notice.region,
            project_type=notice.project_type,
            lower_limit_rate=float(notice.lower_limit_rate),
            participants=notice.participants,
        ),
        strategy=result["strategy"],
        predicted_rate=float(predicted_rate),
        mad_value=float(mad_val),
        prediction_range=[float(rate_lower), float(rate_upper)],
        confidence_grade=confidence_grade,
        fallback_level=fallback_level,
        bids=result["bids"],
    )
