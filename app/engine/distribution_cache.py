"""
app/engine/distribution_cache.py
distribution engine용 인메모리 TTL 캐시.

데이터는 하루 1회 수집 스케줄러 이후에만 변경되므로
TTL(30분) + 수집 후 명시적 무효화 조합으로 운영한다.
"""

import time
from typing import Any

_TTL_SECONDS = 30 * 60  # 30분
_store: dict[str, tuple[Any, float]] = {}


def get(key: str) -> Any | None:
    if key not in _store:
        return None
    value, ts = _store[key]
    if time.time() - ts > _TTL_SECONDS:
        del _store[key]
        return None
    return value


def set(key: str, value: Any) -> None:
    _store[key] = (value, time.time())


def invalidate(key: str | None = None) -> None:
    """key=None이면 전체 캐시 초기화."""
    if key is None:
        _store.clear()
    else:
        _store.pop(key, None)
