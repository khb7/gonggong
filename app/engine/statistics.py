"""
statistics.py
사정률(Adjustment Rate) 통계 계산 모듈.

모든 사정률 값은 float 대신 decimal.Decimal을 사용한다.
이유: 사정률은 소수점 5~6자리까지 의미를 가지며,
     float 연산 오차가 digit_filter 등 하위 모듈 전체로 전파될 수 있다.
"""

from decimal import Decimal


def trimmed_median(rates: list[Decimal], trim_pct: float = 0.05) -> Decimal:
    """
    상·하위 trim_pct% 를 제거한 후 중앙값(Trimmed Median)을 반환한다.
    Ref: 공공입찰.md - 3. 극단값 제거

    Args:
        rates: 사정률 리스트 (Decimal)
        trim_pct: 양쪽 제거 비율 (기본값 5%)

    Returns:
        Trimmed Median (Decimal)

    Raises:
        ValueError: 제거 후 남은 데이터가 없을 경우
    """
    if not rates:
        raise ValueError("rates 리스트가 비어 있습니다.")

    sorted_rates = sorted(rates)
    n = len(sorted_rates)
    cut = int(n * trim_pct)

    trimmed = sorted_rates[cut : n - cut] if cut > 0 else sorted_rates

    if not trimmed:
        raise ValueError(
            f"trim_pct={trim_pct} 적용 후 남은 데이터가 없습니다. "
            f"원본 데이터 수: {n}"
        )

    mid = len(trimmed) // 2
    if len(trimmed) % 2 == 1:
        return trimmed[mid]
    else:
        return (trimmed[mid - 1] + trimmed[mid]) / Decimal("2")


def mad(rates: list[Decimal]) -> Decimal:
    """
    MAD(Median Absolute Deviation)를 계산한다.
    표준편차 대신 사용하며, 극단값(Outlier)에 강건하다.
    Ref: 공공입찰.md - 4. 분산 계산 (MAD)

    MAD = Median( |rate_i - Median(rates)| )

    Args:
        rates: 사정률 리스트 (Decimal)

    Returns:
        MAD 값 (Decimal)
    """
    if not rates:
        raise ValueError("rates 리스트가 비어 있습니다.")

    median = trimmed_median(rates, trim_pct=0.0)  # 전체 데이터로 중앙값 계산
    deviations = [abs(r - median) for r in rates]
    return trimmed_median(deviations, trim_pct=0.0)


def confidence_range(
    median: Decimal, mad_val: Decimal
) -> tuple[Decimal, Decimal]:
    """
    [Median - MAD, Median + MAD] 신뢰 범위를 반환한다.

    Args:
        median: Trimmed Median 값
        mad_val: MAD 값

    Returns:
        (lower_bound, upper_bound) 튜플
    """
    return (median - mad_val, median + mad_val)
