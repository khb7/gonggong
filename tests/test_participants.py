"""
tests/test_participants.py
app/engine/participants.py 단위 테스트
"""

import pytest
from app.engine.participants import estimate_from_counts


def test_estimate_basic():
    """중앙값을 반환한다."""
    assert estimate_from_counts([100, 200, 150]) == 150


def test_estimate_single_value():
    """단일 값이면 그 값을 반환한다."""
    assert estimate_from_counts([300]) == 300


def test_estimate_even_count():
    """짝수 개는 중간 두 값의 평균을 반환한다."""
    assert estimate_from_counts([100, 200]) == 150


def test_estimate_empty_returns_zero():
    """빈 리스트는 0을 반환한다."""
    assert estimate_from_counts([]) == 0


def test_estimate_ignores_outliers():
    """극단값에 강건해야 한다 — 평균이 아닌 중앙값이므로 이상치에 흔들리지 않는다."""
    # 평균: (50+60+70+80+9000) / 5 = 1852 → 신뢰 불가
    # 중앙값: 70 → 올바른 추정
    result = estimate_from_counts([50, 60, 70, 80, 9000])
    assert result == 70


def test_estimate_sorted_correctly():
    """입력 순서와 관계없이 동일한 결과를 반환한다."""
    a = estimate_from_counts([300, 100, 200])
    b = estimate_from_counts([100, 200, 300])
    assert a == b


def test_estimate_large_sample():
    """큰 샘플에서도 중앙값이 올바르게 계산된다."""
    counts = list(range(1, 102))  # 1~101, 중앙값 = 51
    assert estimate_from_counts(counts) == 51
