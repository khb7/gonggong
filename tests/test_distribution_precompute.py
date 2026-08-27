"""
사전계산 히스토그램 경로 (app/db/crud_distribution.py).

참여자 4.5M 행을 요청마다 스캔하면 RAM 1GB 서버가 스래싱으로 멈춘다.
SQL 집계로 메모리는 해결됐지만 속도가 남아(서버 실측 global 69.1s),
넓은 스코프는 `scripts/build_offset_histogram.py` 가 미리 계산해 표에 넣는다.

여기서는 그 표가 **실제로 쓰이는지**, 그리고 없을 때 실시간 경로로
제대로 떨어지는지를 고정한다.
"""

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.models import (
    BidsHistory,
    BidLicenseType,
    BidParticipants,
    OffsetHistogram,
    OffsetScopeStat,
)
from app.db.crud_distribution import (
    get_precomputed_distribution,
    get_precomputed_scope_stat,
    resolve_offset_distribution,
    scope_key_for,
)
import app.engine.distribution_cache as cache

LOWER_LIMIT = Decimal("0.87745")


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.invalidate()
    yield
    cache.invalidate()


async def _add_notice(session, pid: str, *, client_name="발주처", region="경기",
                      project_type="조경", base_price=800_000_000):
    session.add(BidsHistory(
        project_id=pid, client_name=client_name, client_id="None", region=region,
        bid_type="적격심사", price_method="기타", base_price=base_price,
        lower_limit_rate=LOWER_LIMIT, adjustment_rate=Decimal("0.999"),
        winner_price=int(base_price * 0.88), bid_date=date(2025, 5, 1), participants=40,
    ))
    session.add(BidLicenseType(project_id=pid, type_name=project_type))


async def _add_participants(session, pid: str, rates: list[str]):
    for i, r in enumerate(rates, start=1):
        session.add(BidParticipants(
            project_id=pid, rank=i, bid_amount=1_000_000,
            bid_rate=Decimal(r), is_winner=(i == 1),
        ))


# ── scope_key_for ─────────────────────────────────────────────


def test_scope_key_is_shared_between_builder_and_reader():
    """빌더와 조회가 같은 규칙으로 키를 만들어야 한다.

    어긋나면 표는 채워져 있는데 조회가 못 찾고 조용히 느린 경로로 떨어진다.
    증상이 "가끔 느림" 이라 잡기 어렵다.
    """
    assert scope_key_for("global", None, None) == ""
    assert scope_key_for("region", "경기", None) == "경기"
    assert scope_key_for("type_bucket", "조경", 2) == "조경:2"
    # 버킷이 키에 들어가야 한다 — 안 들어가면 버킷별 분포가 서로 덮어쓴다
    assert scope_key_for("type_bucket", "조경", 2) != scope_key_for("type_bucket", "조경", 3)


# ── 조회 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_precomputed_lookup_returns_none_when_absent(db):
    assert await get_precomputed_distribution(db, "global", "") is None
    assert await get_precomputed_scope_stat(db, "global", "") is None


@pytest.mark.asyncio
async def test_precomputed_lookup_returns_bins(db):
    db.add(OffsetHistogram(scope_level="global", scope_key="", offset_pct=0.1,
                           count=100, win_count=5))
    db.add(OffsetHistogram(scope_level="global", scope_key="", offset_pct=-0.2,
                           count=50, win_count=1))
    db.add(OffsetScopeStat(scope_level="global", scope_key="", notices=12, bids=150))
    await db.commit()

    bins = await get_precomputed_distribution(db, "global", "")
    assert [b["offset_pct"] for b in bins] == [-0.2, 0.1], "offset 오름차순이 아니다"
    assert bins[1]["count"] == 100 and bins[1]["win_count"] == 5
    assert await get_precomputed_scope_stat(db, "global", "") == (12, 150)


@pytest.mark.asyncio
async def test_resolve_prefers_precomputed_over_live_scan(db):
    """사전계산이 있으면 참여자 테이블을 스캔하지 않는다.

    참여자 행은 하나도 넣지 않고 사전계산만 넣는다. 실시간 경로를 탔다면
    빈 분포가 나올 것이고, 사전계산을 썼다면 넣어둔 bin 이 나온다.
    """
    db.add(OffsetHistogram(scope_level="region", scope_key="경기", offset_pct=0.3,
                           count=777, win_count=9))
    db.add(OffsetScopeStat(scope_level="region", scope_key="경기", notices=40, bids=777))
    await db.commit()

    bins, scope = await resolve_offset_distribution(db, None, "경기", None, None)

    assert scope.level == "region"
    assert scope.notices == 40 and scope.bids == 777
    assert bins == [{"offset_pct": 0.3, "count": 777, "win_count": 9}]


@pytest.mark.asyncio
async def test_resolve_skips_precomputed_scope_below_minimum(db):
    """사전계산이 있어도 공고 수가 부족하면 그 레벨은 건너뛴다.

    사전계산은 속도를 위한 것이지 채택 기준을 바꾸는 게 아니다.
    """
    db.add(OffsetHistogram(scope_level="region", scope_key="경기", offset_pct=0.3,
                           count=777, win_count=9))
    db.add(OffsetScopeStat(scope_level="region", scope_key="경기", notices=3, bids=777))
    db.add(OffsetHistogram(scope_level="global", scope_key="", offset_pct=0.9,
                           count=5, win_count=1))
    db.add(OffsetScopeStat(scope_level="global", scope_key="", notices=99, bids=5))
    await db.commit()

    bins, scope = await resolve_offset_distribution(db, None, "경기", None, None)

    assert scope.level == "global", "공고 3건짜리 region 이 채택됐다"
    assert bins == [{"offset_pct": 0.9, "count": 5, "win_count": 1}]


@pytest.mark.asyncio
async def test_resolve_falls_back_to_live_when_not_precomputed(db):
    """사전계산이 없으면 실시간 집계로 떨어진다.

    client 레벨은 서버에서도 0.6s 라 일부러 사전계산하지 않는다.
    """
    for i in range(12):
        await _add_notice(db, f"P{i}", client_name="우리발주처")
        await _add_participants(db, f"P{i}", ["0.880"] * 5)
    await db.commit()

    bins, scope = await resolve_offset_distribution(db, "우리발주처", None, None, None)

    assert scope.level == "client"
    assert scope.notices == 12
    assert len(bins) == 1 and bins[0]["count"] == 60
