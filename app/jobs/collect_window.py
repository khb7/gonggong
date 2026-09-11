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
    run_end: date | None = None
    weekdays = 0

    def close():
        nonlocal run_start, run_end, weekdays
        if run_start is not None and run_end is not None:
            ranges.append((run_start, run_end))
        run_start = run_end = None
        weekdays = 0

    while current <= end:
        if current in collected:
            close()
        elif current.weekday() >= 5:
            # 주말은 **후보도 경계도 아니다.**
            #
            # 개찰이 평일에만 있어 토·일은 수집해도 결과가 없다 — DB 전 기간
            # 요일별 공고 수: 월 2,222 화 3,923 수 3,393 목 3,343 금 3,035,
            # 토 0, 일 0. 결과가 없으니 `collected` 에도 영원히 안 들어가고,
            # 그래서 매 실행마다 미수집으로 다시 잡혀 브라우저 세션을 낭비했다.
            #
            # 다만 구간을 쪼개지도 않는다. 금요일과 다음 월요일은 이어진 한
            # 구간이어야 한다 — 쪼개면 세션이 구간마다 새로 뜬다.
            pass
        else:
            if run_start is None:
                run_start = current
                weekdays = 0
            run_end = current
            weekdays += 1
            # max_span 은 이제 **평일 수**로 센다. 브라우저 세션이 버티는
            # 한계는 달력 일수가 아니라 실제로 훑는 공고 양에 가깝다.
            if weekdays == max_span:
                close()
        current += timedelta(days=1)

    close()
    return ranges
