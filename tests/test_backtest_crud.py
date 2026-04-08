"""
before_date 파라미터가 crud 함수에서 정상 동작하는지 검증.
"""
import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.crud import (
    get_rates_by_client,
    get_rates_by_region,
    get_rates_by_type_and_bucket,
    get_all_rates,
)


def _make_db(rows: list) -> AsyncSession:
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(Decimal(str(r)),) for r in rows]
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock(return_value=mock_result)
    return db


def _get_sql(db) -> str:
    """db.execute에 전달된 Select 객체를 SQL 문자열로 컴파일하여 반환."""
    stmt = db.execute.call_args.args[0]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_get_rates_by_client_without_before_date():
    db = _make_db([0.999, 1.001])
    rates = await get_rates_by_client(db, "테스트기관", "건축", 2)
    assert len(rates) == 2
    sql = _get_sql(db)
    assert "bid_date" not in sql


@pytest.mark.asyncio
async def test_get_rates_by_client_with_before_date():
    db = _make_db([0.999])
    rates = await get_rates_by_client(
        db, "테스트기관", "건축", 2, before_date=date(2025, 1, 1)
    )
    assert len(rates) == 1
    sql = _get_sql(db)
    assert "bid_date" in sql


@pytest.mark.asyncio
async def test_get_rates_by_region_with_before_date():
    db = _make_db([0.998, 1.002, 0.997])
    rates = await get_rates_by_region(
        db, "경기", "조경", 1, before_date=date(2025, 1, 1)
    )
    assert len(rates) == 3
    sql = _get_sql(db)
    assert "bid_date" in sql


@pytest.mark.asyncio
async def test_get_rates_by_type_and_bucket_with_before_date():
    db = _make_db([1.0])
    rates = await get_rates_by_type_and_bucket(
        db, "조경", 1, before_date=date(2025, 1, 1)
    )
    assert len(rates) == 1
    sql = _get_sql(db)
    assert "bid_date" in sql


@pytest.mark.asyncio
async def test_get_all_rates_with_before_date():
    db = _make_db([0.999, 1.001])
    rates = await get_all_rates(db, "건축", before_date=date(2025, 1, 1))
    assert len(rates) == 2
    sql = _get_sql(db)
    assert "bid_date" in sql
