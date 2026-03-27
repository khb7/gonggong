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


class FetchedData(BaseModel):
    """G2B에서 파싱한 원본 데이터 (Override 적용 전)."""
    base_price: int
    client_name: str
    region: str
    project_type: str
    lower_limit_rate: float
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
    fallback_level: str = Field(..., description="사용된 Fallback 레벨")

    bids: list[BidItem] = Field(..., description="추천 투찰가 목록 (Aggressive → Safe)")
