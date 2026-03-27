"""
calculator.py
최종 투찰가 계산 모듈.

핵심 공식:
    Final Bid Price = base_price × predicted_rate × (lower_limit_rate + offset)

모든 rate 값은 decimal.Decimal을 사용한다.
"""

from decimal import Decimal, ROUND_DOWN
from app.engine.strategy import select_strategy, select_center_offset, generate_bid_spread
from app.engine.digit_filter import apply_digit_filter

# 전략 레이블 순서 (오직 Aggressive 하나만 사용)
_LABELS = ["Aggressive"]


def calculate_single(
    base_price: int,
    lower_limit_rate: Decimal,
    predicted_rate: Decimal,
    offset: Decimal,
) -> dict:
    """
    단일 Offset으로 투찰가를 계산한다.
    Ref: 공공입찰.md - 9. 최종 투찰 공식

    Final Bid Price = base_price × predicted_rate × (lower_limit_rate + offset)

    Args:
        base_price: 기초금액 (원, int)
        lower_limit_rate: 하한율 (Decimal, 예: Decimal("0.87745"))
        predicted_rate: 사정률 예측값 (Decimal, 예: Decimal("1.00000"))
        offset: 전략 Offset (Decimal)

    Returns:
        {"rate_pct": float, "price_krw": int}
        - rate_pct: 최종 비율 (%, 소수점 3자리)
        - price_krw: 최종 투찰가 (원, 정수 — 소수점 이하 버림)
    """
    combined_rate = lower_limit_rate + offset

    # digit_filter: 데이터 수집 및 가설 검증 단계이므로 active=False로 작동 (필터 발동 여부만 기록)
    combined_rate, triggered_digit_filter = apply_digit_filter(combined_rate, active=False)

    final_price_decimal = Decimal(base_price) * predicted_rate * combined_rate

    # 원화는 소수점 이하 버림 (입찰 시 원 단위 정수)
    price_krw = int(final_price_decimal.to_integral_value(rounding=ROUND_DOWN))

    # 비율은 예가 대비 % (lower_limit_rate + offset) × predicted_rate × 100
    rate_pct = float(round(combined_rate * predicted_rate * 100, 5))

    return {"rate_pct": rate_pct, "price_krw": price_krw, "digit_filter_triggered": triggered_digit_filter}


def calculate_bid_spread(
    base_price: int,
    lower_limit_rate: Decimal,
    predicted_rate: Decimal,
    participants: int,
    mad_val: Decimal,
    step: Decimal = Decimal("0.001"),
    count: int = 1,
) -> dict:
    """
    Multi-Shot Bid Spread를 계산하여 전략별 투찰가 리스트를 반환한다.
    Ref: 공공입찰.md - 10. 최종 프로세스 (Workflow)

    처리 순서:
    1. 경쟁자 수 → 전략 선택 (safe / normal / aggressive)
    2. 전략 → 중심 Offset 결정
    3. 중심 Offset 기준 step 간격 후보 count개 생성 (digit_filter 포함)
    4. 각 후보로 calculate_single 호출

    Args:
        base_price: 기초금액 (원)
        lower_limit_rate: 하한율 (Decimal)
        predicted_rate: 사정률 예측값 (Decimal)
        participants: 경쟁자 수
        mad_val: MAD 값 (Decimal)
        step: Bid Spread 간격 (기본값 0.001)
        count: 생성할 타점 수 (기본값 3)

    Returns:
        {
            "strategy": str,
            "bids": [
                {"label": str, "rate_pct": float, "price_krw": int},
                ...
            ],
        }

    Examples:
        base_price=1_000_000_000, LLR=0.87745, predicted_rate=1.0, participants=152
        → strategy: "aggressive" (항상), center_offset=-MAD
        → spread offsets: [-MAD]
        → bids: Aggressive 1개
    """
    strategy = select_strategy(participants)
    center_offset = select_center_offset(strategy, mad_val)
    spread_offsets = generate_bid_spread(center_offset, step=step, count=count)

    bids = []
    for label, offset in zip(_LABELS, spread_offsets):
        item = calculate_single(base_price, lower_limit_rate, predicted_rate, offset)
        bids.append({"label": label, **item})

    return {"strategy": strategy, "bids": bids}
