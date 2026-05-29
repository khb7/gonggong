"""
tests/test_distribution_cache.py
app/engine/distribution_cache.py 단위 테스트
"""

import pytest
from unittest.mock import patch, AsyncMock
from decimal import Decimal

import app.engine.distribution_cache as cache
from app.db.crud_distribution import get_offset_distribution_cached


@pytest.fixture(autouse=True)
def clear_cache():
    cache.invalidate()
    yield
    cache.invalidate()


# ── get / set ─────────────────────────────────────────────────

def test_cache_miss_returns_none():
    assert cache.get("missing") is None


def test_cache_hit_returns_value():
    cache.set("k", [1, 2, 3])
    assert cache.get("k") == [1, 2, 3]


def test_cache_stores_dict():
    cache.set("k", {"a": 1})
    assert cache.get("k") == {"a": 1}


# ── TTL ───────────────────────────────────────────────────────

def test_cache_within_ttl_returns_value():
    with patch("app.engine.distribution_cache.time") as t:
        t.time.return_value = 0.0
        cache.set("k", "v")
        t.time.return_value = 29 * 60.0  # 29분
        assert cache.get("k") == "v"


def test_cache_expired_returns_none():
    with patch("app.engine.distribution_cache.time") as t:
        t.time.return_value = 0.0
        cache.set("k", "v")
        t.time.return_value = 31 * 60.0  # 31분
        assert cache.get("k") is None


# ── invalidate ────────────────────────────────────────────────

def test_invalidate_specific_key():
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.invalidate("k1")
    assert cache.get("k1") is None
    assert cache.get("k2") == "v2"


def test_invalidate_all():
    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.invalidate()
    assert cache.get("k1") is None
    assert cache.get("k2") is None


def test_invalidate_nonexistent_is_noop():
    cache.invalidate("ghost")  # 예외 없어야 함


# ── get_offset_distribution_cached ───────────────────────────

_MOCK_ROWS = [
    {"bid_rate": Decimal("0.87145"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False},
]


@pytest.mark.asyncio
async def test_cached_calls_db_on_miss():
    """캐시 미스 시 DB 쿼리를 호출한다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_MOCK_ROWS)) as mock_fn:
        result = await get_offset_distribution_cached(db)

    assert result == _MOCK_ROWS
    mock_fn.assert_called_once()


@pytest.mark.asyncio
async def test_cached_skips_db_on_hit():
    """캐시 히트 시 DB 쿼리를 호출하지 않는다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_MOCK_ROWS)) as mock_fn:
        await get_offset_distribution_cached(db)
        await get_offset_distribution_cached(db)  # 두 번째는 캐시에서

    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_cached_refetches_after_invalidation():
    """무효화 후 다음 호출은 DB를 다시 쿼리한다."""
    db = AsyncMock()
    fresh_rows = [{"bid_rate": Decimal("0.88000"), "lower_limit_rate": Decimal("0.87745"), "is_winner": True}]

    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(side_effect=[_MOCK_ROWS, fresh_rows])) as mock_fn:
        await get_offset_distribution_cached(db)
        cache.invalidate()
        result = await get_offset_distribution_cached(db)

    assert result == fresh_rows
    assert mock_fn.call_count == 2
