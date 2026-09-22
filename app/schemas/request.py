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
    a_value: int | None = Field(
        None,
        description=(
            "A값 (원). 투찰율 적용에서 제외되는 법정경비 합계. "
            "공고문에 공개되며, 0이 아니면 낙찰하한가가 (예정가격−A)×하한율+A 로 올라간다."
        ),
        ge=0,
    )
    preprice_rate: Decimal | None = Field(
        None,
        description=(
            "사정률(예정가격/기초금액)을 직접 지정한다. 없으면 고정 상수(100.15%)를 쓴다. "
            "예측값이 아니라 선택이다 — 실제 사정률보다 높아야 투찰가가 하한가 위에 놓인다. "
            "복수예비가격 생성범위가 최대 ±3% 라 그 밖은 오타로 본다."
        ),
        ge=Decimal("0.97"), le=Decimal("1.03"),
    )
    client_name: str | None = Field(None, description="발주처명 (예: 부산광역시)")
    client_id: str | None = Field(None, description="나라장터 발주청 코드 (예: 6110000)")
    region: str | None = Field(None, description="지역명 (예: 서울, 경기)")
    project_type: str | None = Field(None, description="공종 (예: 실내건축, 조경)")
    bid_type: str | None = Field(None, description="입찰방식 (예: 적격심사, 최저가, 협상)")


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
