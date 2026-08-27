"""
calculator.py
최종 투찰가 계산 모듈.

핵심 공식:
    예정가격 추정치 = base_price × predicted_rate
    Final Bid Price = (예정가격 − A값) × (lower_limit_rate + offset) + A값

A값(투찰율 적용 제외 법정경비)이 0이면 아래 기존 공식과 완전히 동일하다.
    Final Bid Price = base_price × predicted_rate × (lower_limit_rate + offset)

Ref: md/reference/공공입찰_제도_가이드.md - 6. A값

모든 rate 값은 decimal.Decimal을 사용한다.
"""

from decimal import Decimal, ROUND_DOWN
from app.engine.strategy import select_strategy, select_center_offset, generate_bid_spread
from app.engine.digit_filter import apply_digit_filter
from app.engine.a_value import bid_price_with_a_value

# 전략 레이블 순서 (오직 Aggressive 하나만 사용)
_LABELS = ["Aggressive"]


def calculate_single(
    base_price: int,
    lower_limit_rate: Decimal,
    predicted_rate: Decimal,
    offset: Decimal,
    a_value: int = 0,
) -> dict:
    """
    단일 Offset으로 투찰가를 계산한다.
    Ref: md/reference/공공입찰_제도_가이드.md - 6. A값

        예정가격 추정치 = base_price × predicted_rate
        Final Bid Price = (예정가격 − A값) × (lower_limit_rate + offset) + A값

    a_value=0이면 기존 공식 `base_price × predicted_rate × (LLR + offset)`과 같다.

    Args:
        base_price: 기초금액 (원, int)
        lower_limit_rate: 법정 하한율 (Decimal, 예: Decimal("0.89745"))
        predicted_rate: 사정률 예측값 (Decimal, 예: Decimal("1.00000"))
        offset: 전략 Offset (Decimal)
        a_value: A값 (원, int). 투찰율 적용에서 제외되는 법정경비 합계.

    Returns:
        {"rate_pct": float, "price_krw": int, ...}
        - rate_pct: 예정가격 대비 최종 비율 (%). A값이 있으면 (LLR+offset)보다 높다.
        - price_krw: 최종 투찰가 (원, 정수 — 소수점 이하 버림)
    """
    combined_rate = lower_limit_rate + offset

    # digit_filter: 데이터 수집 및 가설 검증 단계이므로 active=False로 작동 (필터 발동 여부만 기록)
    combined_rate, triggered_digit_filter = apply_digit_filter(combined_rate, active=False)

    # 개찰 전에는 예정가격을 모르므로 기초금액 × 사정률 예측값으로 추정한다.
    expected_price = int(
        (Decimal(base_price) * predicted_rate).to_integral_value(rounding=ROUND_DOWN)
    )
    a_value = max(0, int(a_value or 0))
    if a_value > expected_price:
        # A값이 예정가격을 넘을 수 없다. 이상값이면 무시하고 A값 없이 계산한다.
        a_value = 0

    price_krw = bid_price_with_a_value(expected_price, a_value, combined_rate)

    # 비율은 예정가격 대비 % — A값이 있으면 실효 비율이 combined_rate보다 높다.
    if expected_price > 0:
        rate_pct = float(round(Decimal(price_krw) / Decimal(expected_price) * 100, 5))
    else:
        rate_pct = float(round(combined_rate * 100, 5))

    return {
        "rate_pct": rate_pct,
        "price_krw": price_krw,
        "digit_filter_triggered": triggered_digit_filter,
        "a_value": a_value,
    }


def calculate_bid_spread(
    base_price: int,
    lower_limit_rate: Decimal,
    predicted_rate: Decimal,
    participants: int,
    mad_val: Decimal,
    step: Decimal = Decimal("0.001"),
    count: int = 1,
    a_value: int = 0,
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
        a_value: A값 (원). 0이면 기존 공식과 동일.

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
        item = calculate_single(base_price, lower_limit_rate, predicted_rate, offset, a_value)
        bids.append({"label": label, **item})

    return {"strategy": strategy, "bids": bids}
