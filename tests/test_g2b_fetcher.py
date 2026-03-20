"""
tests/test_g2b_fetcher.py
g2b_fetcher.py 단위 테스트 — MockG2BFetcher 중심
"""

import pytest
from decimal import Decimal
from app.external.g2b_fetcher import MockG2BFetcher, G2BNoticeData, DEFAULT_PARTICIPANTS


@pytest.fixture
def fetcher():
    return MockG2BFetcher()


# ──────────────────────────────────────────
# MockG2BFetcher 테스트
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_mock_fetch_known_notice(fetcher):
    """등록된 공고 번호는 정확한 데이터를 반환해야 한다."""
    result = await fetcher.fetch("TEST-001")
    assert isinstance(result, G2BNoticeData)
    assert result.base_price == 1_000_000_000
    assert result.client_name == "서울특별시"
    assert result.region == "서울"
    assert result.project_type == "실내건축"
    assert result.lower_limit_rate == Decimal("0.87745")
    assert result.participants == 152


@pytest.mark.asyncio
async def test_mock_fetch_unknown_notice_returns_default(fetcher):
    """등록되지 않은 공고 번호는 기본값을 반환해야 한다."""
    result = await fetcher.fetch("UNKNOWN-999")
    assert isinstance(result, G2BNoticeData)
    assert result.base_price > 0
    assert result.lower_limit_rate > 0
    assert result.participants == DEFAULT_PARTICIPANTS


@pytest.mark.asyncio
async def test_mock_fetch_test002(fetcher):
    """TEST-002 공고는 경기도교육청 데이터를 반환해야 한다."""
    result = await fetcher.fetch("TEST-002")
    assert result.client_name == "경기도교육청"
    assert result.participants == 30


@pytest.mark.asyncio
async def test_mock_lower_limit_rate_is_decimal(fetcher):
    """lower_limit_rate는 반드시 Decimal 타입이어야 한다 (float 오차 방지)."""
    result = await fetcher.fetch("TEST-001")
    assert isinstance(result.lower_limit_rate, Decimal)
