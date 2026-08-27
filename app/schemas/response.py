"""
app/schemas/response.py
투찰가 계산 결과 스키마 (Pydantic)
"""

from pydantic import BaseModel, Field


class BidItem(BaseModel):
    """단일 타점 결과."""
    label: str = Field(..., description="전략 레이블 (Aggressive / Normal / Safe)")
    rate_pct: float = Field(..., description="예가 대비 비율 (%)")
    price_krw: int = Field(..., description="최종 투찰가 (원)")
    digit_filter_triggered: bool = Field(..., description="Digit Filter 발동 여부 (추후 데이터 분석 및 가설 검증용)")
    a_value: int = Field(0, description="계산에 반영된 A값 (원). 0이면 A값 없는 공고")


class FetchedData(BaseModel):
    """G2B에서 파싱한 원본 데이터 (Override 적용 전)."""
    base_price: int
    client_name: str
    region: str
    project_type: str
    # None = 공고에서 낙찰하한율을 확인할 수 없었다 (미개찰 등).
    # `G2BNoticeData.lower_limit_rate` 와 같은 규약이다 — 임의 상수로 채우지 않는다.
    # 이 필드는 **원본 fetch 값**이므로, override 로 계산이 성공해도 여기는 null 일 수 있다.
    lower_limit_rate: float | None
    participants: int


class BidResponse(BaseModel):
    """투찰가 계산 최종 응답."""
    bid_notice_id: str
    mode: str = Field(..., description='"auto" | "override"')
    overridden_fields: list[str] = Field(
        default_factory=list, description="Override된 필드명 목록"
    )
    g2b_fetch_status: str = Field(..., description='"ok" | "failed" | "mock"')
    fetched: FetchedData

    strategy: str = Field(..., description='"safe" | "normal" | "aggressive"')
    predicted_rate: float = Field(..., description="사정률 예측값 (Trimmed Median)")
    mad_value: float = Field(..., description="MAD 값")
    prediction_range: list[float] = Field(..., description="예측 구간 [lower, upper] = predicted_rate ± MAD")
    confidence_grade: str = Field(..., description='신뢰도 등급. 사정률 예측을 끈 뒤로는 항상 "fixed" 다 (T-015)')
    fallback_level: str = Field(..., description='사용된 Fallback 레벨. 사정률 예측을 끈 뒤로는 항상 "fixed" 다 (T-015)')

    bids: list[BidItem] = Field(..., description="추천 투찰가 목록 (Aggressive → Safe)")
