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
#
# ⚠ 공사와 용역·물품 후보를 **반드시 분리해서** 쓴다.
#   섞으면 A값이 붙은 공사 공고의 실효율이 바로 위 용역 후보를 넘어가
#   더 높은 법정율로 오분류되고, 그만큼 A값이 과소평가된다.
#
#   예) 법정 0.89745 + A값 5% → 실효 0.90258
#       섞인 표에서는 0.90000 에 걸려 A값이 21% 과소 산출된다.
#       공사 표에서는 0.89745 로 정확히 맞는다 (다음 후보가 0.88745 뿐).
#
#   실측 검증: A값이 원본에 명시된 151건(Info21c `나의 투찰 성향`)에 대해
#       섞인 표 20개 → 법정율 정확 매칭 30.5%, A값 역산이 실제의 78.8%
#       공사 표 12개 → 법정율 정확 매칭 100%,  A값 역산이 실제의 100%
#   재현: tests/test_a_value.py::test_construction_table_matches_declared_a_value

# 적격심사 '공사' 구간별 하한율 (상향 전/후 모두)
LEGAL_LIMIT_RATES_CONSTRUCTION: tuple[Decimal, ...] = tuple(
    sorted(
        Decimal(v)
        for v in (
            # 상향 전
            "0.79995", "0.80495", "0.81395", "0.83395",
            "0.85495", "0.85995", "0.86745", "0.87745",
            # 2%p 상향 후
            "0.81995", "0.87495", "0.88745", "0.89745",
        )
    )
)

# 용역 · 물품 계열. 공사와 간격이 좁아 같이 쓰면 안 된다.
LEGAL_LIMIT_RATES_SERVICE: tuple[Decimal, ...] = tuple(
    sorted(
        Decimal(v)
        for v in (
            "0.87995", "0.88000", "0.88450", "0.89995",
            "0.90000", "0.91950", "0.92000", "0.95000",
        )
    )
)

# 하위 호환용 합집합. 새 코드에서는 쓰지 말 것 — 위 경고 참조.
LEGAL_LIMIT_RATES: tuple[Decimal, ...] = tuple(
    sorted(LEGAL_LIMIT_RATES_CONSTRUCTION + LEGAL_LIMIT_RATES_SERVICE)
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
    rates: tuple[Decimal, ...] = LEGAL_LIMIT_RATES_CONSTRUCTION,
) -> Decimal | None:
    """
    실효 하한율에서 법정 낙찰하한율을 결정한다.

    Args:
        effective_rate: 낙찰하한가 / 예정가격 (A값이 녹아든 값)
        declared: 원본 파일의 `낙찰하한율` 컬럼값. 있으면 최우선 사용.
        rates: 후보표. 기본은 **공사**다 — 이 프로젝트가 실내건축·조경 공종
               대상이기 때문이다. 용역·물품 공고는 `LEGAL_LIMIT_RATES_SERVICE`를
               명시적으로 넘긴다. 두 표를 합쳐 쓰면 A값이 과소평가된다
               (LEGAL_LIMIT_RATES_CONSTRUCTION 위 주석 참조).

    Returns:
        법정 낙찰하한율. 판별 불가 시 None.

    A ≥ 0 이므로 effective_rate ≥ 법정 하한율이 항상 성립한다.
    따라서 effective_rate 이하의 후보 중 가장 큰 값을 고른다.

    ⚠ 한계: A값이 커서 effective_rate가 바로 위 후보를 넘어서면
      더 높은 법정 하한율로 잘못 매칭되어 A값이 과소평가된다.
      후보표를 공종에 맞게 좁힐수록, 그리고 declared가 있으면 안전하다.
    """
    if effective_rate is None or effective_rate <= 0:
        return None

    if declared is not None and declared > 0:
        # 신고된 법정 하한율이 실효 하한율보다 높으면 모순이므로 신뢰하지 않는다.
        if declared <= effective_rate + _RATE_TOLERANCE:
            return declared

    candidates = [r for r in rates if r <= effective_rate + _RATE_TOLERANCE]
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


def derive_a_value_from_bid_rate(
    expected_price: int,
    bid_price: int,
    bid_rate: Decimal,
) -> int | None:
    """조정 투찰율에서 A값을 **추측 없이** 역산한다.

    원본 `투찰율(%)`(→ `bid_participants.bid_rate`)은 이미 A값이 제거된 값이다:

        bid_rate = (투찰금액 − A) / (예정가격 − A)
      ⇒ A = (투찰금액 − bid_rate × 예정가격) / (1 − bid_rate)

    `derive_a_value()` 는 낙찰하한가에서 출발해 **법정 하한율을 후보표로 추측**해야 하고,
    후보 간격이 좁은 구간에서 한 칸 위로 오분류되면 A값이 과소 산출된다.
    이 함수는 그 추측 단계가 없어 정확하다.

    Args:
        expected_price: 예정가격 (원)
        bid_price: 그 업체의 투찰금액 (원)
        bid_rate: 그 업체의 조정 투찰율

    Returns:
        A값 (원). 계산 불가하거나 비현실적이면 None.
        잔차 수준(_A_VALUE_NOISE_FLOOR 미만)이면 0.
    """
    if expected_price <= 0 or bid_price <= 0:
        return None
    r = Decimal(str(bid_rate))
    if not (0 < r < 1):
        return None

    a_value = (Decimal(bid_price) - r * Decimal(expected_price)) / (Decimal(1) - r)

    # A값은 법정경비 합계라 음수일 수 없고, 예정가격의 25%를 넘는 일도 없다.
    # 벗어나면 입력이 오염된 것이므로 추정하지 않고 포기한다.
    if a_value < 0 or a_value >= Decimal(expected_price) * Decimal("0.25"):
        return None
    if a_value < _A_VALUE_NOISE_FLOOR:
        return 0
    return int(a_value.to_integral_value(rounding=ROUND_HALF_UP))


def snap_legal_limit_rate(
    rate: Decimal,
    rates: tuple[Decimal, ...] = LEGAL_LIMIT_RATES_CONSTRUCTION,
    tolerance: Decimal = Decimal("0.0005"),
) -> Decimal | None:
    """계산된 하한율을 가장 가까운 규정값으로 맞춘다.

    `resolve_legal_limit_rate()` 는 "이하 후보 중 최대"를 고르는 **추정**이라
    A값이 녹아든 실효율을 입력으로 받는다. 이 함수는 A값을 이미 정확히 알 때
    쓰는 것으로, 계산값이 규정값 근처가 아니면 None 을 반환해 오염을 드러낸다.

    Args:
        rate: (낙찰하한가 − A) / (예정가격 − A) 로 계산한 값
        rates: 후보표 (기본 공사)
        tolerance: 이 안에 들어야 규정값으로 인정한다

    Returns:
        규정 하한율. 어느 후보와도 tolerance 밖이면 None.
    """
    if rate is None or not (0 < rate < 1):
        return None
    nearest = min(rates, key=lambda x: abs(x - rate))
    return nearest if abs(nearest - rate) <= tolerance else None


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
