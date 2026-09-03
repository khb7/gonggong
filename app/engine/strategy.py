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
    중심 Offset 값. **전략과 무관하게 항상 0 이다.**

    offset 은 `combined_rate = 낙찰하한율 + offset` 으로 쓰인다.
    0 은 "가정한 사정률에서의 낙찰하한가에 정확히 붙인다" 는 뜻이다.

    ## 왜 0 인가

    예전에는 safe/aggressive 가 `+MAD`(0.486%p)를 돌려줬다. 하한가보다 그만큼
    위에 투찰하면 유효하기는 하지만 **이길 자리가 아니다.** 실측(12,010 공고)에서
    낙찰자는 낙찰하한가 위 **+0.016%**(중앙값)에 붙어 있다. 0.486%p 는 그보다
    30 배 멀다.

    ## 위험 조절은 offset 이 아니라 사정률로 한다

    투찰가는 두 단계로 정해진다:

        예정가격 = 기초금액 × 사정률(c)          ← 여기가 불확실. 제도가 만드는 난수
        투찰가   = (예정가격 − A) × (r + offset) + A

    유효/무효를 가르는 건 c 다 — `c ≥ 실제사정률` 이라야 유효하다.
    offset 을 올려 안전을 사려 하면 c 를 올리는 것과 효과가 겹치면서
    낙찰선에서만 멀어진다. 그래서 조절 손잡이를 c 하나로 모았다
    (`app/api/v1/bidding.py::FIXED_PREPRICE_RATE`, 자사 151건 스윕 최적 100.15%).

    `select_strategy()` 가 항상 "aggressive" 를 반환하므로 실사용 경로는
    어차피 하나뿐이다. 인자는 호출부 호환을 위해 남긴다.
    타점 선택 자체는 분포 화면(`/bid/distribution`)이 담당한다.

    Args:
        strategy: 전략명. 현재 결과에 영향을 주지 않는다.
        mad_val: MAD 값. 현재 결과에 영향을 주지 않는다.

    Returns:
        Decimal("0")
    """
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
