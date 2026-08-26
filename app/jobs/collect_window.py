"""
app/jobs/collect_window.py
수집할 날짜 구간 계산.

PC 가 며칠 꺼져 있어도 다음 실행 때 공백을 메우기 위해, 수집 이력에 없는
날짜만 골라 연속 구간으로 묶는다. DB 도 네트워크도 건드리지 않는다.
"""

from datetime import date, timedelta


def pending_ranges(
    collected: set[date],
    start: date,
    end: date,
    max_span: int = 7,
) -> list[tuple[date, date]]:
    """start~end 중 collected 에 없는 날짜를 연속 구간으로 묶어 돌려준다.

    Args:
        collected: 이미 수집이 끝난 날짜 집합
        start:     조회 시작일 (포함)
        end:       조회 종료일 (포함)
        max_span:  구간 하나의 최대 일수. 긴 공백을 한 번에 넘기면
                   브라우저 세션이 버티지 못하므로 잘라 준다.

    Returns:
        [(구간시작, 구간끝), ...] — 빈 날짜가 없으면 빈 리스트
    """
    ranges: list[tuple[date, date]] = []
    current = start
    run_start: date | None = None
    run_len = 0

    def close():
        nonlocal run_start, run_len
        if run_start is not None:
            ranges.append((run_start, run_start + timedelta(days=run_len - 1)))
            run_start = None
            run_len = 0

    while current <= end:
        if current in collected:
            close()
        else:
            if run_start is None:
                run_start = current
                run_len = 0
            run_len += 1
            if run_len == max_span:
                close()
        current += timedelta(days=1)

    close()
    return ranges
