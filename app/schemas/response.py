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


class PrepriceHistogramOut(BaseModel):
    """과거 공고의 실제 사정률 히스토그램 (T-038).

    사용자가 고른 사정률 c 가 과거 공고에서 어땠을지 보여주는 재료다.
    투찰가 유효 조건은 `c ≥ 실제 사정률` 하나뿐이라, 분포 위에 c 를 그으면
    왼쪽이 유효·오른쪽이 무효다. 유효율·근접률은 프론트가 이 개수로 계산한다.
    """
    law: str = Field(..., description="어느 계약법 공고를 모았나. unknown 이면 전체")
    n: int = Field(..., description="표본 공고 수")
    bin_start: float = Field(..., description="첫 bin 의 하한 (0.970)")
    bin_width: float = Field(..., description="bin 폭 (0.0005 = 0.05%p)")
    counts: list[int] = Field(..., description="bin 별 공고 수 (120개)")


class BidResponse(BaseModel):
    """투찰가 계산 최종 응답."""
    bid_notice_id: str
    mode: str = Field(..., description='"auto" | "override"')
    overridden_fields: list[str] = Field(
        default_factory=list, description="Override된 필드명 목록"
    )
    g2b_fetch_status: str = Field(..., description='"ok" | "failed" | "mock"')
    fetched: FetchedData

    base_price: int = Field(
        ...,
        description=(
            "계산에 실제로 쓴 기초금액(원). override 를 반영한 값이라 "
            "`fetched.base_price`(원본 조회값)와 다를 수 있다"
        ),
    )

    strategy: str = Field(..., description='"safe" | "normal" | "aggressive"')
    predicted_rate: float = Field(
        ...,
        description=(
            "투찰가 계산에 쓴 사정률. 예측값이 아니다 — 전역 고정 상수(T-015)거나 "
            "사용자가 직접 넣은 값(T-038)이다. "
            "분포의 중심이 아니라 하한가 미달을 피하기 위한 안전 여유값이다."
        ),
    )
    contract_law: str = Field(
        ...,
        description=(
            '발주처에서 판별한 적용 계약법. "national"(±2%) | "local"(±3%) '
            '| "agency"(지방조달청 대행) | "unknown". 사정률 산포가 여기서 따라온다'
        ),
    )
    mad_value: float = Field(
        ..., description="사정률 MAD. 계약법별 실측값이라 공고마다 다르다"
    )
    prediction_range: list[float] = Field(..., description="예측 구간 [lower, upper] = predicted_rate ± MAD")
    confidence_grade: str = Field(..., description='신뢰도 등급. 사정률 예측을 끈 뒤로는 항상 "fixed" 다 (T-015)')
    fallback_level: str = Field(
        ...,
        description='사정률의 출처. "fixed"(고정 상수, T-015) | "override"(직접 입력, T-038)',
    )
    preprice_histogram: PrepriceHistogramOut = Field(
        ..., description="같은 계약법 공고의 실제 사정률 히스토그램 (T-038)"
    )

    bids: list[BidItem] = Field(..., description="추천 투찰가 목록 (Aggressive → Safe)")
