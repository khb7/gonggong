"""
tests/test_api_distribution.py
POST /api/v1/bid/distribution 엔드포인트 통합 테스트.

DB 의존성은 AsyncMock으로 대체.
G2BFetcher는 MockG2BFetcher 사용.
"""

import contextlib

import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
from app.db.crud_distribution import DistributionScope
from app.external.g2b_fetcher import MockG2BFetcher


# ──────────────────────────────────────────
# 공통 픽스처
# ──────────────────────────────────────────

async def _mock_db():
    yield AsyncMock()


app.dependency_overrides[get_db] = _mock_db

_MOCK_ROWS = [
    {"bid_rate": Decimal("0.87145"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False},
    {"bid_rate": Decimal("0.87145"), "lower_limit_rate": Decimal("0.87745"), "is_winner": True},
    {"bid_rate": Decimal("0.87245"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False},
    {"bid_rate": Decimal("0.87245"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False},
]
# 위 rows → -0.6% bin: count=2, win_count=1 / -0.5% bin: count=2, win_count=0


@contextlib.contextmanager
def _dist(
    rows,
    avg: int = 150,
    scope: DistributionScope | None = None,
    global_rows=None,
    sigma: Decimal | None = None,
):
    """분포 조회 계층을 통째로 대체한다.

    scope 를 주면 fallback 레벨을 강제할 수 있고, global_rows 로 낙찰 빈도
    계산에 쓰이는 전체 표본을 따로 지정할 수 있다.
    sigma 를 주면 내 위치의 사정률 오차 밴드가 계산된다 (기본은 밴드 없음).
    """
    scope = scope or DistributionScope(
        level="global", label=None, notices=len(rows), bids=len(rows)
    )
    targets = {
        "resolve_offset_distribution": AsyncMock(return_value=(rows, scope)),
        "get_offset_distribution_cached": AsyncMock(
            return_value=global_rows if global_rows is not None else rows
        ),
        "get_avg_participants": AsyncMock(return_value=avg),
        "get_adjustment_rate_sigma": AsyncMock(return_value=sigma),
    }
    with contextlib.ExitStack() as stack:
        for name, mock in targets.items():
            stack.enter_context(patch(f"app.api.v1.distribution.{name}", mock))
        yield


@pytest.fixture
def client():
    mock_settings = type("S", (), {"use_mock_g2b": True, "G2B_API_KEY": ""})()
    with patch("app.api.v1.distribution._get_fetcher", return_value=MockG2BFetcher()), \
         patch("app.api.v1.distribution.settings", mock_settings), \
         TestClient(app) as c:
        yield c


def _call(client, body: dict):
    return client.post("/api/v1/bid/distribution", json=body)


# ──────────────────────────────────────────
# 기본 동작
# ──────────────────────────────────────────

def test_distribution_returns_200(client):
    """기본 요청에서 200과 응답 구조를 반환한다."""
    with _dist(_MOCK_ROWS, avg=150):
        resp = _call(client, {"bid_notice_id": "TEST-001"})

    assert resp.status_code == 200


def test_distribution_response_fields(client):
    """응답에 필수 필드가 모두 존재한다."""
    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert "bid_notice_id" in data
    assert "base_price" in data
    assert "lower_limit_rate" in data
    assert "estimated_participants" in data
    assert "g2b_fetch_status" in data
    assert "distribution" in data
    assert "data_quality" in data
    assert "my_position" in data


def test_distribution_bins_populated(client):
    """DB rows에서 distribution 목록이 올바르게 생성된다."""
    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert len(data["distribution"]) == 2
    bin_offsets = [b["offset_pct"] for b in data["distribution"]]
    assert pytest.approx(-0.6, abs=0.05) in bin_offsets
    assert pytest.approx(-0.5, abs=0.05) in bin_offsets


def test_distribution_bin_fields(client):
    """각 bin에 offset_pct, count, win_count, historical_win_rate가 있다."""
    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    for b in data["distribution"]:
        assert "offset_pct" in b
        assert "count" in b
        assert "win_count" in b
        assert "historical_win_rate" in b


def test_distribution_historical_win_rate_value(client):
    """-0.6% bin: count=2, win_count=1 → historical_win_rate=50.0."""
    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    bins = {round(b["offset_pct"], 1): b for b in data["distribution"]}
    assert bins[-0.6]["historical_win_rate"] == pytest.approx(50.0, abs=0.1)
    assert bins[-0.5]["historical_win_rate"] == pytest.approx(0.0, abs=0.1)


def test_distribution_data_quality_total_bids(client):
    """data_quality.total_bids는 전체 참여자 수다."""
    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["data_quality"]["total_bids"] == 4


def test_distribution_estimated_participants(client):
    """estimated_participants는 DB에서 조회한 값을 반환한다."""
    with _dist(_MOCK_ROWS, avg=320):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["estimated_participants"] == 320


# ──────────────────────────────────────────
# my_position
# ──────────────────────────────────────────

def test_distribution_my_position_none_when_no_price(client):
    """my_bid_price 없으면 my_position은 null이다."""
    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["my_position"] is None


def test_distribution_my_position_populated(client):
    """my_bid_price 제공 시 my_position에 올바른 필드가 채워진다."""
    # TEST-001: base_price=1,000,000,000 / llr=0.87745
    # offset -0.6% → bid = 1,000,000,000 × (0.87745 - 0.006) = 871,450,000
    my_bid = int(1_000_000_000 * (0.87745 - 0.006))

    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid}).json()

    pos = data["my_position"]
    assert pos is not None
    assert "offset_pct" in pos
    assert "estimated_price" in pos
    assert "percentile" in pos
    assert "historical_win_rate" in pos
    assert "sample_count" in pos


def test_distribution_band_null_without_sigma(client):
    """σ를 못 구하면 오차 밴드 필드는 null이다 — 근거 없는 폭을 그리지 않는다."""
    my_bid = int(1_000_000_000 * (0.87745 - 0.006))

    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid}).json()

    assert data["rate_sigma"] is None
    assert data["my_position"]["offset_low_pct"] is None
    assert data["my_position"]["offset_high_pct"] is None


def test_distribution_band_populated_with_sigma(client):
    """σ가 있으면 내 위치를 점이 아니라 ±1σ 폭으로 함께 반환한다."""
    my_bid = int(1_000_000_000 * (0.87745 - 0.006))

    with _dist(_MOCK_ROWS, avg=150, sigma=Decimal("0.0072")):
        data = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid}).json()

    pos = data["my_position"]
    assert data["rate_sigma"] == pytest.approx(0.0072)
    assert pos["offset_low_pct"] < pos["offset_pct"] < pos["offset_high_pct"]
    # 밴드 폭이 bin 해상도(0.1%)보다 훨씬 넓어야 "점으로 그리면 안 된다"가 성립한다
    assert pos["offset_high_pct"] - pos["offset_low_pct"] > 1.0


def test_distribution_my_position_out_of_range_returns_null(client):
    """분포 범위 밖 투찰가이면 my_position은 null이다."""
    # 매우 높은 가격 → 분포에 없는 offset
    my_bid = int(1_000_000_000 * (0.87745 + 0.050))

    with _dist(_MOCK_ROWS, avg=150):
        data = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid}).json()

    assert data["my_position"] is None


# ──────────────────────────────────────────
# 빈 데이터
# ──────────────────────────────────────────

def test_distribution_empty_db(client):
    """DB에 데이터 없으면 distribution은 빈 리스트, my_position은 null이다."""
    with _dist([], avg=0):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["distribution"] == []
    assert data["my_position"] is None
    assert data["data_quality"]["total_bids"] == 0


# ──────────────────────────────────────────
# 입력 검증
# ──────────────────────────────────────────

def test_distribution_missing_bid_notice_id_returns_422(client):
    """bid_notice_id 없으면 422를 반환한다."""
    resp = _call(client, {})
    assert resp.status_code == 422


# ──────────────────────────────────────────
# fallback 레벨 노출
# ──────────────────────────────────────────

def test_data_quality_reports_global_level_by_default(client):
    """필터가 잡히지 않으면 global 레벨로 응답한다."""
    with _dist(_MOCK_ROWS):
        dq = _call(client, {"bid_notice_id": "TEST-001"}).json()["data_quality"]

    assert dq["distribution_level"] == "global"
    assert dq["distribution_label"] is None
    assert dq["win_rate_level"] == "global"


def test_data_quality_reports_client_level(client):
    """발주처 레벨이 채택되면 레벨·필터값·공고 수를 응답에 담는다."""
    scope = DistributionScope(level="client", label="서울주택도시공사", notices=40, bids=14989)
    with _dist(_MOCK_ROWS, scope=scope):
        dq = _call(client, {"bid_notice_id": "TEST-001"}).json()["data_quality"]

    assert dq["distribution_level"] == "client"
    assert dq["distribution_label"] == "서울주택도시공사"
    assert dq["sample_notices"] == 40


def test_count_is_filtered_but_win_rate_is_global(client):
    """막대 높이는 필터 표본, 낙찰 빈도는 글로벌 표본에서 온다."""
    # 필터된 표본: -0.6% 에 2건, 낙찰 0건
    filtered = [
        {"bid_rate": Decimal("0.87145"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False},
        {"bid_rate": Decimal("0.87145"), "lower_limit_rate": Decimal("0.87745"), "is_winner": False},
    ]
    # 글로벌 표본(_MOCK_ROWS): -0.6% 에 2건 중 낙찰 1건 → 50%
    scope = DistributionScope(level="client", label="발주처A", notices=40, bids=2)
    with _dist(filtered, scope=scope, global_rows=_MOCK_ROWS):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    bins = {round(b["offset_pct"], 1): b for b in data["distribution"]}
    # 필터 표본에 없는 -0.5% bin 은 막대가 생기지 않는다
    assert set(bins) == {-0.6}
    assert bins[-0.6]["count"] == 2                                    # 필터 기준
    assert bins[-0.6]["historical_win_rate"] == pytest.approx(50.0)    # 글로벌 기준
    assert data["data_quality"]["total_bids"] == 2
    assert data["data_quality"]["win_rate_bids"] == 4


def test_avg_participants_failure_does_not_break_response(client):
    """참여자 평균 조회가 실패해도 분포는 정상 응답한다."""
    scope = DistributionScope(level="global", label=None, notices=1, bids=4)
    with patch("app.api.v1.distribution.resolve_offset_distribution",
               AsyncMock(return_value=(_MOCK_ROWS, scope))), \
         patch("app.api.v1.distribution.get_offset_distribution_cached",
               AsyncMock(return_value=_MOCK_ROWS)), \
         patch("app.api.v1.distribution.get_adjustment_rate_sigma",
               AsyncMock(return_value=None)),          patch("app.api.v1.distribution.get_avg_participants",
               AsyncMock(side_effect=RuntimeError("relation does not exist"))):
        resp = _call(client, {"bid_notice_id": "TEST-001"})

    assert resp.status_code == 200
    assert resp.json()["estimated_participants"] == 0
    assert len(resp.json()["distribution"]) == 2


def test_sigma_failure_does_not_break_response(client):
    """σ 조회가 실패해도 분포는 정상 응답한다 — 밴드만 사라진다."""
    my_bid = int(1_000_000_000 * (0.87745 - 0.006))
    scope = DistributionScope(level="global", label=None, notices=1, bids=4)
    with patch("app.api.v1.distribution.resolve_offset_distribution",
               AsyncMock(return_value=(_MOCK_ROWS, scope))),          patch("app.api.v1.distribution.get_offset_distribution_cached",
               AsyncMock(return_value=_MOCK_ROWS)),          patch("app.api.v1.distribution.get_avg_participants",
               AsyncMock(return_value=150)),          patch("app.api.v1.distribution.get_adjustment_rate_sigma",
               AsyncMock(side_effect=RuntimeError("stddev_samp is not defined"))):
        resp = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid})

    assert resp.status_code == 200
    data = resp.json()
    assert data["rate_sigma"] is None
    assert data["my_position"]["offset_low_pct"] is None
