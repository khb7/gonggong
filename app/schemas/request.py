"""
app/schemas/request.py
입찰 계산 요청 스키마 (Pydantic)
"""

from decimal import Decimal
from pydantic import BaseModel, Field


class BidOverrides(BaseModel):
    """
    Manual Override 필드.
    존재하는 필드만 G2B Fetcher 결과를 덮어쓴다.
    """
    base_price: int | None = Field(None, description="기초금액 (원)", gt=0)
    lower_limit_rate: Decimal | None = Field(
        None, description="낙찰하한율 (예: 0.87745)", gt=0, lt=1
    )
    participants: int | None = Field(None, description="참여 업체 수", gt=0)
    client_name: str | None = Field(None, description="발주처명 (예: 부산광역시)")
    region: str | None = Field(None, description="지역명 (예: 부산광역시[26000])")
    project_type: str | None = Field(None, description="분류/공종 (예: 건축공사)")


class BidRequest(BaseModel):
    """
    투찰가 계산 요청.

    Mode 1 (Auto-Fetch): bid_notice_id 만 전달
    Mode 2 (Override):   bid_notice_id + overrides 전달
    """
    bid_notice_id: str = Field(..., description="나라장터 공고 번호", examples=["2026031112345"])
    overrides: BidOverrides | None = Field(
        None,
        description="G2B 파싱값을 덮어쓸 Override 필드 (선택사항)",
    )
