"""
tests/test_distribution_crud.py
app/db/crud_distribution.py 의 조회 계층 검증.

실제 in-memory SQLite 에 표본을 넣고 돌린다. 여기서 잡으려는 버그가
"어떤 행이 걸러지는가" 이므로, SQL 문자열이 아니라 반환된 행을 본다.
"""

import pytest
import pytest_asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.db.models import BidsHistory, BidParticipants, BidLicenseType
from app.db.crud_distribution import (
    get_offset_distribution,
    get_avg_participants,
    resolve_offset_distribution,
)


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


async def _add_notice(
    session,
    project_id: str,
    *,
    client_name: str = "테스트발주처",
    client_id: str = "None",
    region: str = "경기",
    price_method: str = "기타",
    base_price: int = 800_000_000,
    project_type: str = "조경",
    participants: int = 40,
):
    session.add(
        BidsHistory(
            project_id=project_id,
            client_name=client_name,
            client_id=client_id,
            region=region,
            bid_type="적격심사",
            price_method=price_method,
            base_price=base_price,
            lower_limit_rate=LOWER_LIMIT,
            adjustment_rate=Decimal("0.999"),
            winner_price=int(base_price * 0.88),
            bid_date=date(2025, 5, 1),
            participants=participants,
        )
    )
    session.add(BidLicenseType(project_id=project_id, type_name=project_type))


async def _add_participants(
    session, project_id: str, rates: list[str], *, rank_from: int = 1
):
    for i, r in enumerate(rates):
        session.add(
            BidParticipants(
                project_id=project_id,
                rank=rank_from + i,
                bid_amount=1_000_000,
                bid_rate=Decimal(r),
                is_winner=(rank_from + i == 1),
            )
        )


# ──────────────────────────────────────────
# 1. bid_rate 이상치 (T-010)
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_offset_rows_exclude_dummy_bid_rate(db):
    """bid_amount 더미값(99999999999999)이 만든 거대 bid_rate 는 분포에서 빠진다.

    실 DB 에 2,271 행 있고, 이것들이 offset_pct 를 +1729% 까지 밀어 올린다.
    """
    await _add_notice(db, "P1")
    await _add_participants(db, "P1", ["0.880", "0.881", "0.882"])
    await _add_participants(db, "P1", ["452586.75392"], rank_from=4)  # 더미
    await db.commit()

    rows = await get_offset_distribution(db, client_name="테스트발주처")

    assert all(r["bid_rate"] <= Decimal("1.05") for r in rows), (
        f"상한 초과 행이 남았다: {[str(r['bid_rate']) for r in rows]}"
    )


@pytest.mark.asyncio
async def test_offset_rows_exclude_implausibly_low_bid_rate(db):
    """투찰률이 될 수 없는 저가 행은 분포에서 빠진다.

    낙찰하한율은 낮아도 0.6 대다. bid_rate 0.03 은 금액 자리수가 깨진 행이고,
    남겨 두면 offset_pct 하한을 -84% 까지 늘여 히스토그램 축을 망친다.
    """
    await _add_notice(db, "P1")
    await _add_participants(db, "P1", ["0.880", "0.881", "0.882"])
    await _add_participants(db, "P1", ["0.033"], rank_from=4)  # 자리수 깨짐
    await db.commit()

    rows = await get_offset_distribution(db, client_name="테스트발주처")

    assert all(r["bid_rate"] >= Decimal("0.5") for r in rows), (
        f"저가 이상치가 남았다: {[str(r['bid_rate']) for r in rows]}"
    )


@pytest.mark.asyncio
async def test_offset_rows_exclude_negative_bid_rate(db):
    """rank 파싱 오류가 만든 음수 bid_rate 는 분포에서 빠진다.

    실 DB 에 232 행 있고, offset_pct 를 -1033% 까지 끌어내린다.
    """
    await _add_notice(db, "P1")
    await _add_participants(db, "P1", ["0.880", "0.881", "0.882"])
    await _add_participants(db, "P1", ["-9.46"], rank_from=4)  # 파싱 오류
    await db.commit()

    rows = await get_offset_distribution(db, client_name="테스트발주처")

    assert all(r["bid_rate"] > Decimal("0") for r in rows), (
        f"음수 행이 남았다: {[str(r['bid_rate']) for r in rows]}"
    )


# ──────────────────────────────────────────
# 2. get_avg_participants strict filter (T-009)
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_avg_participants_counts_etc_price_method(db):
    """price_method 가 '기타' 인 공고도 평균 참여자 수에 들어간다.

    Info21c CSV 에 예정가격결정방식 컬럼이 없어 실 DB 의 97% 가 '기타' 다.
    분포 쿼리(_RELAX_FILTERS)는 이미 '기타'를 허용하는데 이 함수만 빼면,
    표본이 붕괴해 참여자 수가 실제의 1/10 로 떨어진다.
    """
    for i in range(12):
        await _add_notice(db, f"P{i}", price_method="기타", participants=40)
    await db.commit()

    avg = await get_avg_participants(
        db, client_name="테스트발주처", region="경기", project_type="조경", bucket_id=3
    )

    assert avg == 40, f"'기타' 공고가 표본에서 빠졌다 (avg={avg})"


@pytest.mark.asyncio
async def test_avg_participants_not_weighted_by_license_count(db):
    """공고에 붙은 공종 수가 평균 참여자 수를 부풀리지 않는다.

    발주처·지역 레벨은 공종 조건을 쓰지 않는데도 BidLicenseType 을 join 하면,
    공종이 여러 개인 공고가 그 수만큼 중복 계산된다. 실 DB 는 공고 하나에
    공종이 최대 14 개 붙어 있어, 경기 지역 평균이 375.9 → 520.1 로 뜬다.
    """
    # 참여자 10 명 공고 10 건: 공종 1 개씩
    for i in range(10):
        await _add_notice(db, f"S{i}", participants=10, project_type="조경")
    # 참여자 100 명 공고 2 건: 공종 3 개씩 → join 하면 6 건으로 부풀려진다
    for i in range(2):
        await _add_notice(db, f"B{i}", participants=100, project_type="조경")
        db.add(BidLicenseType(project_id=f"B{i}", type_name="건축"))
        db.add(BidLicenseType(project_id=f"B{i}", type_name="토목"))
    await db.commit()

    avg = await get_avg_participants(
        db, client_name="테스트발주처", region="경기", project_type="조경", bucket_id=3
    )

    # 진짜 평균 = (10*10 + 100*2) / 12 = 25
    # 공종 가중이 걸리면   = (10*10 + 100*6) / 16 = 43
    assert avg == 25, f"공종 수만큼 가중됐다 (avg={avg}, 기대 25)"


# ──────────────────────────────────────────
# 3. client 레벨이 발주처를 실제로 가르는가
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_client_level_isolates_by_client_name(db):
    """client 레벨이 채택되면 다른 발주처 행이 섞이지 않는다.

    발주처를 client_name 으로 가른다. client_id 로 가르면 안 된다 —
    실 DB 는 12,445 행 전부 client_id='None' 이라 필터가 서면 전 발주처가
    한 덩어리로 매칭되고 client 레벨이 사실상 global 이 된다.
    """
    # 레벨 채택 기준은 참여자 행 수가 아니라 공고 수(_MIN_DIST_NOTICES=10)다.
    for i in range(12):
        await _add_notice(db, f"MINE-{i}", client_name="우리발주처")
        await _add_participants(db, f"MINE-{i}", ["0.880"] * 20)
    for i in range(12):
        await _add_notice(db, f"OTHER-{i}", client_name="남의발주처")
        await _add_participants(db, f"OTHER-{i}", ["0.900"] * 20)
    await db.commit()

    rows, scope = await resolve_offset_distribution(
        db, "우리발주처", "경기", "조경", 3
    )

    assert scope.level == "client"
    assert scope.label == "우리발주처"
    assert all(r["bid_rate"] == Decimal("0.880") for r in rows), (
        "다른 발주처 행이 섞였다 — client 레벨이 발주처를 못 가른다"
    )
