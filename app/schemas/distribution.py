"""
app/schemas/distribution.py
POST /api/v1/bid/distribution 요청/응답 스키마
"""

from pydantic import BaseModel, Field
from app.schemas.request import BidOverrides


class DistributionRequest(BaseModel):
    bid_notice_id: str = Field(..., description="나라장터 공고 번호")
    overrides: BidOverrides | None = Field(None, description="수동 입력 (기초금액, 하한율 등)")
    my_bid_price: int | None = Field(None, description="내 투찰가 (원) — 입력 시 my_position 계산", gt=0)


class OffsetBucketResponse(BaseModel):
    offset_pct: float = Field(..., description="bin 중심 offset (%, 예: -0.6)")
    count: int = Field(..., description="해당 구간 과거 참여 건수")
    win_count: int = Field(..., description="해당 구간 과거 낙찰 건수")
    historical_win_rate: float | None = Field(
        None, description="과거 낙찰 빈도 (%) — count=0이면 null. 낙찰 확률이 아님"
    )


class MyPositionResponse(BaseModel):
    offset_pct: float = Field(..., description="내 투찰가의 offset (%)")
    estimated_price: int = Field(..., description="기초금액 × (하한율 + offset) (원)")
    percentile: float = Field(..., description="내 가격보다 낮은 과거 입찰 비율 (%) — 공격성 지표")
    historical_win_rate: float = Field(..., description="해당 구간 과거 낙찰 빈도 (%)")
    sample_count: int = Field(..., description="해당 구간 참여 건수 — 값 신뢰도 판단용")


class DataQuality(BaseModel):
    total_bids: int = Field(..., description="분포 계산에 사용된 참여자 수 (선택된 레벨 기준)")
    distribution_level: str = Field(
        "global",
        description='막대 높이(count)에 사용된 fallback 레벨: "client" | "region" | "type_bucket" | "global"',
    )
    distribution_label: str | None = Field(
        None, description="해당 레벨의 필터값 (global이면 null)"
    )
    sample_notices: int = Field(
        0, description="선택된 레벨의 공고 수 — 레벨 채택 기준이 되는 값"
    )
    win_rate_level: str = Field(
        "global",
        description="historical_win_rate 계산에 사용된 레벨. 표본 요구량이 달라 항상 global이다",
    )
    win_rate_bids: int = Field(
        0, description="낙찰 빈도 계산에 사용된 전체 참여자 수"
    )


class DistributionResponse(BaseModel):
    bid_notice_id: str
    base_price: int
    lower_limit_rate: float = Field(..., description="법정 낙찰하한율 (A값 제외 기준선)")
    a_value: int = Field(0, description="계산에 반영된 A값 (원). 0이면 A값 없는 공고")
    estimated_participants: int = Field(..., description="이번 공고 예상 참여자 수 (과거 유사 공고 평균)")
    g2b_fetch_status: str = Field(..., description='"ok" | "failed" | "mock"')
    distribution: list[OffsetBucketResponse]
    data_quality: DataQuality
    my_position: MyPositionResponse | None = None
