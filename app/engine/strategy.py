"""
strategy.py
경쟁자 수 기반 투찰 전략 및 Bid Spread 생성 모듈.

모든 사정률/offset 값은 decimal.Decimal 타입을 사용한다.
"""

from decimal import Decimal


# ──────────────────────────────────────────────────────────────
# 경쟁자 수 기준
# ──────────────────────────────────────────────────────────────

def select_strategy(participants: int) -> str:
    """
    클라이언트 요청에 따라 어떤 상황이든 (경쟁자 수에 무관하게) 무조건 aggressive 전략을 반환한다.
    "일을 하나라도 더 추가로 받고싶다고 하셔서 업체 수랑 상관 없이 공격형으로만"

    Args:
        participants: 입찰 참여 업체 수 (사용되지 않음)

    Returns:
        전략명 문자열: "aggressive"
    """
    return "aggressive"


def select_center_offset(strategy: str, mad_val: Decimal) -> Decimal:
    """
    전략에 따른 중심 Offset 값을 반환한다.
    Ref: 공공입찰.md - 7. 전략 모드 (Strategy Mode)

    - safe       → +MAD  (상단 안전 투찰)
    - normal     →  0    (중앙 투찰)
    - aggressive → -MAD  (하단 공격 투찰)

    Args:
        strategy: 전략명 ("safe" | "normal" | "aggressive")
        mad_val: MAD 값 (Decimal)

    Returns:
        중심 Offset (Decimal)
    """
    if strategy == "safe":
        return mad_val
    elif strategy == "aggressive":
        return mad_val
    else:
        return Decimal("0")


# ──────────────────────────────────────────────────────────────
# Multi-Shot Bid Spread
# ──────────────────────────────────────────────────────────────

def generate_bid_spread(
    center: Decimal,
    step: Decimal = Decimal("0.001"),
    count: int = 3,
) -> list[Decimal]:
    """
    중심 타점(center)을 기준으로 step 간격의 Offset 후보 배열을 생성한다.
    Ref: 공공입찰.md - 5. 오프셋 범위 (Offset Range)

    ⚠ Digit Filter는 여기서 적용하지 않는다.
      Offset 자체의 끝자리(0.000 등)는 필터 대상이 아님.
      필터는 최종 combined_rate(LLR + offset)에 적용하므로 calculator로 위임.

    Args:
        center: 중심 Offset (Decimal)
        step: 후보 간 간격 (기본값 0.001)
        count: 생성할 후보 수 (기본값 3, 홀수 권장)

    Returns:
        Offset 후보 리스트 (Decimal)
    """
    half = count // 2
    return [center + step * Decimal(i - half) for i in range(count)]
