"""
digit_filter.py
소수점 끝자리 블랙리스트 회피 모듈.

⚠ Float 오차 방지 원칙:
   if rate in {0.745} 방식은 0.7450000000000001 오차로 필터가 뚫릴 수 있다.
   → 소수점 끝 3자리를 '문자열'로 추출하여 비교한다.
   → 모든 rate 값은 decimal.Decimal 타입으로 전달해야 한다.
"""

from decimal import Decimal

# 사람/매크로가 습관적으로 사용하는 '게으른 끝자리' 블랙리스트
# 문자열 3자리로 관리 — float 오차 원천 차단
DIGIT_BLACKLIST: frozenset[str] = frozenset({"000", "500", "745", "777"})

# 최대 재귀 깊이 (연속 Shift 횟수 제한)
_MAX_SHIFT = 20


def apply_digit_filter(
    rate: Decimal,
    blacklist: frozenset[str] = DIGIT_BLACKLIST,
    _depth: int = 0,
) -> tuple[Decimal, bool]:
    """
    사정률(rate)의 소수점 끝 3자리를 문자열로 추출해 블랙리스트와 비교.
    해당하면 +0.001 Shift 후 재귀 검사. 안전한 값과 Shift 여부를 반환.
    Ref: 공공입찰.md - 8. Digit Filter (동가 회피)

    Args:
        rate: 검사할 사정률 (Decimal)
        blacklist: 끝자리 블랙리스트 (기본값: DIGIT_BLACKLIST)
        _depth: 내부 재귀 깊이 추적 (직접 사용 금지)

    Returns:
        (filtered_rate, was_shifted) 튜플
        - filtered_rate: 안전한 사정률 값
        - was_shifted: 한 번이라도 Shift가 발생했으면 True

    Raises:
        RuntimeError: _MAX_SHIFT 초과 시 (블랙리스트가 너무 촘촘한 경우)

    Examples:
        >>> apply_digit_filter(Decimal("0.87745"))
        (Decimal("0.87746"), True)

        >>> apply_digit_filter(Decimal("0.87746"))
        (Decimal("0.87746"), False)
    """
    if _depth > _MAX_SHIFT:
        raise RuntimeError(
            f"Digit Filter가 {_MAX_SHIFT}회 Shift 후에도 안전한 값을 찾지 못했습니다. "
            f"블랙리스트를 확인하세요: {blacklist}"
        )

    # 소수점 이하 문자열 추출 → 끝 3자리 슬라이싱 (float 오차 없음)
    rate_str = str(rate)
    if "." in rate_str:
        decimal_part = rate_str.split(".")[1]
        tail = decimal_part[-3:].ljust(3, "0")  # 소수 자릿수 부족 시 0 패딩
    else:
        tail = "000"

    if tail in blacklist:
        shifted_rate, _ = apply_digit_filter(
            rate + Decimal("0.001"), blacklist, _depth + 1
        )
        return shifted_rate, True

    return rate, (_depth > 0)
