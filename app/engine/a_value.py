"""
app/engine/a_value.py
A값(법정경비) 처리 모듈.

A값은 투찰율 적용에서 제외되는 법정경비 7항목의 합계다.
    국민연금 · 건강보험 · 노인장기요양보험 · 퇴직공제부금비
    · 산업안전보건관리비 · 안전관리비 · 품질관리비

적격심사 낙찰하한가는 예정가격에 하한율을 그냥 곱한 값이 아니다:

    낙찰하한가 = (예정가격 − A) × r + A          (r = 법정 낙찰하한율)

따라서 실효 하한율은 A값이 있으면 법정 하한율보다 항상 높다:

    effective_rate = 낙찰하한가 / 예정가격 = r + (A / 예정가격) × (1 − r)

A값을 무시하고 `예정가격 × r`로 투찰하면 하한가 미달로 부적격 탈락한다.

Ref: md/reference/공공입찰_제도_가이드.md - 6. A값
"""

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

# ──────────────────────────────────────────────────────────────
# 법정 낙찰하한율 후보표
# ──────────────────────────────────────────────────────────────
# 낙찰하한가만 있고 법정 하한율 컬럼이 없는 소스(Info21c `입찰리스트` 엑셀)에서
# 법정 하한율을 역추정하기 위한 후보 목록이다.
#
# ⚠ 이 표는 추정용 보조 수단이다. 원본에 `낙찰하한율` 컬럼이 있으면
#   반드시 그 값을 우선 사용한다(resolve_legal_limit_rate의 declared 인자).
#
# 출처: 국가/지방계약 적격심사 구간별 하한율 + DB 실측 빈출값
#       (2025-07-08 지방계약 / 2026-01-30 국가계약 +2%p 상향 전후 값 모두 포함)
LEGAL_LIMIT_RATES: tuple[Decimal, ...] = tuple(
    sorted(
        Decimal(v)
        for v in (
            # 적격심사 공사 — 상향 전
            "0.79995", "0.80495", "0.81395", "0.83395",
            "0.85495", "0.85995", "0.86745", "0.87745",
            # 적격심사 공사 — 2%p 상향 후
            "0.81995", "0.87495", "0.88745", "0.89745",
            # 용역 · 기타
            "0.87995", "0.88000", "0.88450", "0.89995",
            "0.90000", "0.91950", "0.92000", "0.95000",
        )
    )
)

# 하한율 매칭 허용 오차. 낙찰하한가는 원 단위 절사되므로
# effective_rate가 법정값보다 아주 미세하게 낮게 나올 수 있다.
_RATE_TOLERANCE = Decimal("0.00002")

# 이 값 미만의 역산 A값은 절사 잔차로 보고 0으로 취급한다 (원).
_A_VALUE_NOISE_FLOOR = 1000

# Info21c가 공고명 뒤에 붙이는 A값 적용 태그
_A_VALUE_TAG = "[A값"


def has_a_value_tag(notice_name: str | None) -> bool:
    """
    공고명에 Info21c의 `[A값]` 태그가 있는지 판별한다.

    Info21c `입찰리스트` 리포트는 공고명 뒤에 속성 태그를 붙인다.
    예) "학생회관 승강기 설치 공사 [제한][A값][순]"

    공고명이 잘려 `[A값` 까지만 남는 경우가 있어 닫는 괄호는 보지 않는다.
    """
    if not notice_name:
        return False
    return _A_VALUE_TAG in str(notice_name)


def resolve_legal_limit_rate(
    effective_rate: Decimal,
    declared: Decimal | None = None,
) -> Decimal | None:
    """
    실효 하한율에서 법정 낙찰하한율을 결정한다.

    Args:
        effective_rate: 낙찰하한가 / 예정가격 (A값이 녹아든 값)
        declared: 원본 파일의 `낙찰하한율` 컬럼값. 있으면 최우선 사용.

    Returns:
        법정 낙찰하한율. 판별 불가 시 None.

    A ≥ 0 이므로 effective_rate ≥ 법정 하한율이 항상 성립한다.
    따라서 effective_rate 이하의 후보 중 가장 큰 값을 고른다.

    ⚠ 한계: A값이 커서 effective_rate가 바로 위 후보를 넘어서면
      더 높은 법정 하한율로 잘못 매칭되어 A값이 과소평가된다.
      declared가 있으면 이 문제가 발생하지 않는다.
    """
    if effective_rate is None or effective_rate <= 0:
        return None

    if declared is not None and declared > 0:
        # 신고된 법정 하한율이 실효 하한율보다 높으면 모순이므로 신뢰하지 않는다.
        if declared <= effective_rate + _RATE_TOLERANCE:
            return declared

    candidates = [r for r in LEGAL_LIMIT_RATES if r <= effective_rate + _RATE_TOLERANCE]
    if not candidates:
        return None
    return candidates[-1]


def derive_a_value(
    expected_price: int,
    lower_limit_price: int,
    legal_limit_rate: Decimal,
) -> int:
    """
    낙찰하한가에서 A값을 역산한다.

        낙찰하한가 = (예정가격 − A) × r + A
      ⇒ A = (낙찰하한가 − 예정가격 × r) / (1 − r)

    Args:
        expected_price: 예정가격 (원)
        lower_limit_price: 낙찰하한가 (원)
        legal_limit_rate: 법정 낙찰하한율 r

    Returns:
        A값 (원, 0 이상). 계산 불가하거나 잔차 수준이면 0.
    """
    if expected_price <= 0 or lower_limit_price <= 0:
        return 0
    r = Decimal(str(legal_limit_rate))
    if not (0 < r < 1):
        return 0

    numerator = Decimal(lower_limit_price) - Decimal(expected_price) * r
    a_value = numerator / (Decimal(1) - r)

    if a_value < _A_VALUE_NOISE_FLOOR:
        return 0
    return int(a_value.to_integral_value(rounding=ROUND_HALF_UP))


def effective_limit_rate(
    expected_price: int,
    a_value: int,
    legal_limit_rate: Decimal,
) -> Decimal:
    """
    A값을 반영한 실효 하한율을 계산한다.

        effective = r + (A / 예정가격) × (1 − r)

    A값이 0이면 법정 하한율과 같다.
    """
    r = Decimal(str(legal_limit_rate))
    if expected_price <= 0 or a_value <= 0:
        return r
    return r + (Decimal(a_value) / Decimal(expected_price)) * (Decimal(1) - r)


def bid_price_with_a_value(
    expected_price: int,
    a_value: int,
    rate: Decimal,
) -> int:
    """
    A값을 반영한 투찰가를 계산한다.

        투찰가 = (예정가격 − A) × rate + A

    a_value=0이면 `예정가격 × rate`와 동일하다 (하위 호환).

    Args:
        expected_price: 예정가격 (원). 개찰 전이면 기초금액 × 사정률 추정치.
        a_value: A값 (원)
        rate: 적용 비율 (법정 하한율 + offset)

    Returns:
        투찰가 (원, 소수점 이하 버림)
    """
    r = Decimal(str(rate))
    if a_value <= 0:
        price = Decimal(expected_price) * r
    else:
        price = (Decimal(expected_price) - Decimal(a_value)) * r + Decimal(a_value)
    return int(price.to_integral_value(rounding=ROUND_DOWN))


def split_limit_rates(
    expected_price: int,
    lower_limit_price: int | None,
    declared_limit_rate: Decimal | None,
) -> tuple[Decimal | None, Decimal | None, int]:
    """
    한 행의 하한율을 (법정, 실효, A값)으로 분리한다.

    ETL 진입점. 낙찰하한가가 없으면 declared를 법정=실효로 그대로 쓴다.

    Args:
        expected_price: 예정가격 (원)
        lower_limit_price: 낙찰하한가 (원). 없으면 None.
        declared_limit_rate: 원본의 `낙찰하한율` 컬럼값 (소수). 없으면 None.

    Returns:
        (legal_limit_rate, effective_limit_rate, a_value)
        판별 불가한 항목은 None / 0.
    """
    if not lower_limit_price or expected_price <= 0:
        # 낙찰하한가가 없으면 A값을 알 수 없다. 신고값을 양쪽에 그대로 둔다.
        return declared_limit_rate, declared_limit_rate, 0

    eff = Decimal(lower_limit_price) / Decimal(expected_price)
    legal = resolve_legal_limit_rate(eff, declared_limit_rate)
    if legal is None:
        return declared_limit_rate, eff, 0

    a_value = derive_a_value(expected_price, lower_limit_price, legal)
    return legal, eff, a_value
