"""
tests/test_collect_window.py
app/jobs/collect_window.py — 수집할 날짜 구간 계산.
"""

from datetime import date

from app.jobs.collect_window import pending_ranges


def test_all_days_missing_becomes_one_range():
    """전부 미수집이면 한 구간으로 묶인다."""
    result = pending_ranges(set(), date(2026, 1, 1), date(2026, 1, 5))

    assert result == [(date(2026, 1, 1), date(2026, 1, 5))]


def test_collected_days_are_skipped():
    """이미 수집한 날짜는 빠지고, 남은 날짜만 구간이 된다."""
    collected = {date(2026, 1, 2), date(2026, 1, 3)}

    result = pending_ranges(collected, date(2026, 1, 1), date(2026, 1, 5))

    assert result == [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2026, 1, 4), date(2026, 1, 5)),
    ]


def test_everything_collected_returns_empty():
    """빈 날짜가 없으면 아무것도 수집하지 않는다."""
    collected = {date(2026, 1, 1), date(2026, 1, 2)}

    result = pending_ranges(collected, date(2026, 1, 1), date(2026, 1, 2))

    assert result == []


def test_long_gap_is_split_by_max_span():
    """긴 공백은 max_span 일 단위로 잘린다.

    8 개월을 한 번에 주면 브라우저 세션이 버티지 못한다.
    """
    result = pending_ranges(set(), date(2026, 1, 1), date(2026, 1, 10), max_span=4)

    assert result == [
        (date(2026, 1, 1), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 8)),
        (date(2026, 1, 9), date(2026, 1, 10)),
    ]
