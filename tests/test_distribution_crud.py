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


def _total(bins: list[dict]) -> int:
    """집계된 bin 목록의 총 참여자 수.

    get_offset_distribution 은 SQL 에서 집계해 bin 을 돌려준다(원시 행이 아니다).
    글로벌 스코프 4,490,350 행을 파이썬으로 올리면 RAM 1GB 서버가 멈추기 때문이다.
    """
    return sum(b["count"] for b in bins)


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

    bins = await get_offset_distribution(db, client_name="테스트발주처")

    assert _total(bins) == 3, f"더미 행이 집계에 남았다: {bins}"
    assert max(b["offset_pct"] for b in bins) < 100, (
        f"더미 행이 offset 축을 밀어 올렸다: {bins}"
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

    bins = await get_offset_distribution(db, client_name="테스트발주처")

    assert _total(bins) == 3, f"저가 이상치가 집계에 남았다: {bins}"
    assert min(b["offset_pct"] for b in bins) > -50, (
        f"저가 이상치가 offset 축을 끌어내렸다: {bins}"
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

    bins = await get_offset_distribution(db, client_name="테스트발주처")

    assert _total(bins) == 3, f"음수 행이 집계에 남았다: {bins}"
    assert min(b["offset_pct"] for b in bins) > -50, (
        f"음수 행이 offset 축을 끌어내렸다: {bins}"
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

    bins, scope = await resolve_offset_distribution(db, "우리발주처", "경기")

    assert scope.level == "client"
    assert scope.label == "우리발주처"
    # 우리발주처는 전부 0.880 → offset 하나뿐. 남의발주처(0.900)가 섞이면 bin 이 늘어난다.
    assert len(bins) == 1, f"다른 발주처 행이 섞였다 — client 레벨이 발주처를 못 가른다: {bins}"
    assert _total(bins) == 12 * 20


# ──────────────────────────────────────────
# 4. 하한율 신뢰성 (낙찰자 불변식)
# ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_offset_rows_exclude_notice_with_impossible_winner(db):
    """낙찰자가 법정 하한율보다 낮은 공고는 통째로 빠진다.

    하한 미달은 실격이라 낙찰자가 될 수 없다. 그런 공고는 legal_limit_rate 가
    틀린 것이고, offset 좌표계 자체가 밀려 있어 히스토그램을 오염시킨다.

    실측(12,445 공고 중 261건 = 2.1%)을 제외했을 때
    낙찰자 offset 음수 비율이 비A값 그룹에서 18.0% → 0.0% 로 떨어졌다.
    """
    # 정상 공고 — 낙찰자가 하한율 위
    await _add_notice(db, "OK1")
    await _add_participants(db, "OK1", ["0.878", "0.880", "0.885"])

    # 오염 공고 — 낙찰자(rank 1)가 하한율 아래
    await _add_notice(db, "BAD1")
    await _add_participants(db, "BAD1", ["0.870", "0.880", "0.885"])
    await db.commit()

    bins = await get_offset_distribution(db, client_name="테스트발주처")

    # 오염 공고는 낙찰자뿐 아니라 그 공고의 모든 참여자가 빠져야 한다
    assert _total(bins) == 3, f"오염 공고 행이 남았다: {bins}"
    # 남은 낙찰자는 정상 공고의 0.878 하나뿐이고 하한율 위에 있다
    assert sum(b["win_count"] for b in bins) == 1
    assert min(b["offset_pct"] for b in bins if b["win_count"]) >= 0


@pytest.mark.asyncio
async def test_offset_rows_keep_winner_within_rounding_tolerance(db):
    """원 단위 절사로 아주 미세하게 밑도는 낙찰자는 살린다.

    낙찰하한가는 원 단위로 절사되므로 투찰율이 법정값을 1e-5 수준으로
    밑돌 수 있다. 이걸 오염으로 취급하면 정상 공고가 대량으로 빠진다.
    """
    await _add_notice(db, "EDGE1")
    # 0.87744 = 하한율보다 0.00001 낮다 (_INVARIANT_TOLERANCE = 0.00002 이내)
    await _add_participants(db, "EDGE1", ["0.87744", "0.880"])
    await db.commit()

    bins = await get_offset_distribution(db, client_name="테스트발주처")
    assert _total(bins) == 2, f"허용 오차 안의 공고가 빠졌다: {bins}"
