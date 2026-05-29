"""
app/engine/participants.py
참여자 수 추정 모듈.

DB에서 가져온 과거 참여자 수 목록을 받아 추정값을 반환한다.
평균 대신 중앙값을 사용해 이상치(극단적 대규모 공고 등)에 강건하다.
"""


def estimate_from_counts(counts: list[int]) -> int:
    """
    과거 참여자 수 목록에서 중앙값 기반 추정값을 반환한다.

    Args:
        counts: 과거 공고별 참여자 수 목록

    Returns:
        추정 참여자 수 (빈 리스트면 0)
    """
    if not counts:
        return 0

    sorted_counts = sorted(counts)
    n = len(sorted_counts)
    mid = n // 2

    if n % 2 == 1:
        return sorted_counts[mid]
    return (sorted_counts[mid - 1] + sorted_counts[mid]) // 2
