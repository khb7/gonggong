"""
tests/test_distribution_cache.py
app/engine/distribution_cache.py 단위 테스트
"""

import pytest
from unittest.mock import patch, AsyncMock
from decimal import Decimal

import app.engine.distribution_cache as cache
from app.db.crud_distribution import (
    get_offset_distribution_cached,
    resolve_offset_distribution,
)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.invalidate()
    yield
    cache.invalidate()


@pytest.fixture(autouse=True)
def no_precomputed():
    """사전계산 표는 "비어 있음" 으로 둔다.

    이 파일은 캐시와 fallback 결정 로직만 본다. db 가 AsyncMock 이라
    사전계산 조회가 실제 SQL 을 타면 코루틴이 그대로 흘러 터진다.
    사전계산 경로 자체는 tests/test_distribution_precompute.py 에서 검증한다.
    """
    with patch("app.db.crud_distribution.get_precomputed_distribution",
               AsyncMock(return_value=None)),          patch("app.db.crud_distribution.get_precomputed_scope_stat",
               AsyncMock(return_value=None)):
        yield


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


# ── 캐시 키 필터별 분리 ───────────────────────────────────────

_ROWS_A = [{"bid_rate": Decimal("0.87145"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False}]
_ROWS_B = [{"bid_rate": Decimal("0.88000"), "lower_limit_rate": Decimal("0.87745"), "is_winner": True}]


@pytest.mark.asyncio
async def test_cache_key_separated_by_client():
    """발주처가 다르면 캐시가 섞이지 않는다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(side_effect=[_ROWS_A, _ROWS_B])) as mock_fn:
        a = await get_offset_distribution_cached(db, client_name="발주처A")
        b = await get_offset_distribution_cached(db, client_name="발주처B")

    assert a == _ROWS_A
    assert b == _ROWS_B
    assert mock_fn.call_count == 2


@pytest.mark.asyncio
async def test_cache_key_client_does_not_pollute_global():
    """발주처 조회가 글로벌 캐시를 오염시키지 않는다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(side_effect=[_ROWS_A, _ROWS_B])) as mock_fn:
        scoped = await get_offset_distribution_cached(db, client_name="발주처A")
        glob = await get_offset_distribution_cached(db)

    assert scoped == _ROWS_A
    assert glob == _ROWS_B
    assert mock_fn.call_count == 2


@pytest.mark.asyncio
async def test_cache_key_same_client_hits_cache():
    """같은 발주처 재조회는 DB를 다시 치지 않는다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_ROWS_A)) as mock_fn:
        await get_offset_distribution_cached(db, client_name="발주처A")
        await get_offset_distribution_cached(db, client_name="발주처A")

    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_cache_key_separated_by_type_and_bucket():
    """공종이 같아도 버킷이 다르면 캐시가 분리된다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(side_effect=[_ROWS_A, _ROWS_B])) as mock_fn:
        b2 = await get_offset_distribution_cached(db, project_type="실내건축", bucket_id=2)
        b3 = await get_offset_distribution_cached(db, project_type="실내건축", bucket_id=3)

    assert b2 == _ROWS_A
    assert b3 == _ROWS_B
    assert mock_fn.call_count == 2


# ── resolve_offset_distribution fallback ─────────────────────

@pytest.mark.asyncio
async def test_resolve_uses_client_when_enough_notices():
    """발주처 공고 수가 기준 이상이면 발주처 레벨을 채택한다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.count_offset_distribution",
               AsyncMock(return_value=(40, 14989))), \
         patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_ROWS_A)):
        rows, scope = await resolve_offset_distribution(db, "발주처A", "서울", "실내건축", 3)

    assert rows == _ROWS_A
    assert scope.level == "client"
    assert scope.label == "발주처A"
    assert scope.notices == 40


@pytest.mark.asyncio
async def test_resolve_falls_back_to_global_when_sparse():
    """모든 레벨이 표본 미달이면 글로벌로 떨어진다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.count_offset_distribution",
               AsyncMock(return_value=(2, 500))), \
         patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_ROWS_B)):
        rows, scope = await resolve_offset_distribution(db, "발주처A", "서울", "실내건축", 3)

    assert rows == _ROWS_B
    assert scope.level == "global"
    assert scope.label is None


@pytest.mark.asyncio
async def test_resolve_skips_client_and_uses_region():
    """발주처는 미달이고 지역이 충분하면 지역 레벨을 쓴다."""
    db = AsyncMock()
    # 호출 순서: client(미달) → region(충분)
    with patch("app.db.crud_distribution.count_offset_distribution",
               AsyncMock(side_effect=[(3, 700), (58, 20000)])), \
         patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_ROWS_A)):
        rows, scope = await resolve_offset_distribution(db, "발주처A", "서울", "실내건축", 3)

    assert scope.level == "region"
    assert scope.label == "서울"
    assert scope.notices == 58


@pytest.mark.asyncio
async def test_resolve_counts_notices_not_rows():
    """공고 1건에 참여자가 수백 명이어도 공고 수가 미달이면 채택하지 않는다."""
    db = AsyncMock()
    with patch("app.db.crud_distribution.count_offset_distribution",
               AsyncMock(return_value=(1, 246))), \
         patch("app.db.crud_distribution.get_offset_distribution",
               AsyncMock(return_value=_ROWS_B)):
        _, scope = await resolve_offset_distribution(db, "발주처A", None, None, None)

    assert scope.level == "global"
