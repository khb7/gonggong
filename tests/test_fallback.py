"""
tests/test_fallback.py
fallback.py 단위 테스트 — DB를 Mock으로 대체하여 DB 없이 실행
"""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.data.fallback import (
    get_rates_with_fallback,
    LEVEL_CLIENT,
    LEVEL_REGION,
    LEVEL_BUCKET,
    LEVEL_GLOBAL,
    LEVEL_NONE,
)

# 샘플 사정률 리스트 (20건 이상)
ENOUGH_RATES = [Decimal(str(1.0 + i * 0.001)) for i in range(25)]
EMPTY_RATES: list = []


def _make_db():
    """비어있는 AsyncSession Mock."""
    return AsyncMock()


# ──────────────────────────────────────────
# Fallback 우선순위 테스트
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_fallback_uses_client_when_enough_data():
    """발주처 데이터가 충분하면(≥20) client 레벨을 사용해야 한다."""
    db = _make_db()
    with patch("app.data.fallback.get_rates_by_client", return_value=ENOUGH_RATES), \
         patch("app.data.fallback.get_rates_by_region", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_all_rates", return_value=EMPTY_RATES):

        rates, level = await get_rates_with_fallback(db, "서울특별시", "서울", "실내건축", 2)
        assert level == LEVEL_CLIENT
        assert len(rates) == len(ENOUGH_RATES)


@pytest.mark.asyncio
async def test_fallback_falls_to_region_when_client_insufficient():
    """발주처 데이터 부족 → 지역 데이터로 Fallback해야 한다."""
    db = _make_db()
    with patch("app.data.fallback.get_rates_by_client", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_region", return_value=ENOUGH_RATES), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_all_rates", return_value=EMPTY_RATES):

        rates, level = await get_rates_with_fallback(db, "신규기관", "서울", "실내건축", 2)
        assert level == LEVEL_REGION


@pytest.mark.asyncio
async def test_fallback_falls_to_bucket_when_region_insufficient():
    """지역 데이터 부족 → 공종+버킷으로 Fallback해야 한다."""
    db = _make_db()
    with patch("app.data.fallback.get_rates_by_client", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_region", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=ENOUGH_RATES), \
         patch("app.data.fallback.get_all_rates", return_value=EMPTY_RATES):

        rates, level = await get_rates_with_fallback(db, "신규기관", "신규지역", "실내건축", 2)
        assert level == LEVEL_BUCKET


@pytest.mark.asyncio
async def test_fallback_falls_to_global_when_all_insufficient():
    """모든 레벨 부족 → 전체 데이터 Fallback해야 한다."""
    db = _make_db()
    with patch("app.data.fallback.get_rates_by_client", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_region", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_all_rates", return_value=ENOUGH_RATES):

        rates, level = await get_rates_with_fallback(db, "신규기관", "신규지역", "실내건축", 2)
        assert level == LEVEL_GLOBAL


@pytest.mark.asyncio
async def test_fallback_returns_none_when_no_data():
    """모든 레벨에 데이터 없으면 ([], LEVEL_NONE)을 반환해야 한다."""
    db = _make_db()
    with patch("app.data.fallback.get_rates_by_client", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_region", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_all_rates", return_value=EMPTY_RATES):

        rates, level = await get_rates_with_fallback(db, "신규기관", "신규지역", "실내건축", 2)
        assert level == LEVEL_NONE
        assert rates == []


@pytest.mark.asyncio
async def test_fallback_min_sample_size_boundary():
    """정확히 19건이면 부족 → 20건이면 충분 경계 케이스 검증."""
    db = _make_db()
    rates_19 = [Decimal("1.000")] * 19
    rates_20 = [Decimal("1.000")] * 20

    # 19건: client 부족 → region으로 fallback
    with patch("app.data.fallback.get_rates_by_client", return_value=rates_19), \
         patch("app.data.fallback.get_rates_by_region", return_value=rates_20), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=EMPTY_RATES), \
         patch("app.data.fallback.get_all_rates", return_value=EMPTY_RATES):

        _, level = await get_rates_with_fallback(db, "기관", "서울", "실내건축", 2)
        assert level == LEVEL_REGION
