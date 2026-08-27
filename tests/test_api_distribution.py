"""
tests/test_api_distribution.py
POST /api/v1/bid/distribution 엔드포인트 통합 테스트.

DB 의존성은 AsyncMock으로 대체.
G2BFetcher는 MockG2BFetcher 사용.
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
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
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        resp = _call(client, {"bid_notice_id": "TEST-001"})

    assert resp.status_code == 200


def test_distribution_response_fields(client):
    """응답에 필수 필드가 모두 존재한다."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
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
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert len(data["distribution"]) == 2
    bin_offsets = [b["offset_pct"] for b in data["distribution"]]
    assert pytest.approx(-0.6, abs=0.05) in bin_offsets
    assert pytest.approx(-0.5, abs=0.05) in bin_offsets


def test_distribution_bin_fields(client):
    """각 bin에 offset_pct, count, win_count, historical_win_rate가 있다."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    for b in data["distribution"]:
        assert "offset_pct" in b
        assert "count" in b
        assert "win_count" in b
        assert "historical_win_rate" in b


def test_distribution_historical_win_rate_value(client):
    """-0.6% bin: count=2, win_count=1 → historical_win_rate=50.0."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    bins = {round(b["offset_pct"], 1): b for b in data["distribution"]}
    assert bins[-0.6]["historical_win_rate"] == pytest.approx(50.0, abs=0.1)
    assert bins[-0.5]["historical_win_rate"] == pytest.approx(0.0, abs=0.1)


def test_distribution_data_quality_total_bids(client):
    """data_quality.total_bids는 전체 참여자 수다."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["data_quality"]["total_bids"] == 4


def test_distribution_estimated_participants(client):
    """estimated_participants는 DB에서 조회한 값을 반환한다."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=320)):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["estimated_participants"] == 320


# ──────────────────────────────────────────
# my_position
# ──────────────────────────────────────────

def test_distribution_my_position_none_when_no_price(client):
    """my_bid_price 없으면 my_position은 null이다."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001"}).json()

    assert data["my_position"] is None


def test_distribution_my_position_populated(client):
    """my_bid_price 제공 시 my_position에 올바른 필드가 채워진다."""
    # TEST-001: base_price=1,000,000,000 / llr=0.87745
    # offset -0.6% → bid = 1,000,000,000 × (0.87745 - 0.006) = 871,450,000
    my_bid = int(1_000_000_000 * (0.87745 - 0.006))

    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid}).json()

    pos = data["my_position"]
    assert pos is not None
    assert "offset_pct" in pos
    assert "estimated_price" in pos
    assert "percentile" in pos
    assert "historical_win_rate" in pos
    assert "sample_count" in pos


def test_distribution_my_position_out_of_range_returns_null(client):
    """분포 범위 밖 투찰가이면 my_position은 null이다."""
    # 매우 높은 가격 → 분포에 없는 offset
    my_bid = int(1_000_000_000 * (0.87745 + 0.050))

    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=(_MOCK_ROWS, "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=150)):
        data = _call(client, {"bid_notice_id": "TEST-001", "my_bid_price": my_bid}).json()

    assert data["my_position"] is None


# ──────────────────────────────────────────
# 빈 데이터
# ──────────────────────────────────────────

def test_distribution_empty_db(client):
    """DB에 데이터 없으면 distribution은 빈 리스트, my_position은 null이다."""
    with patch("app.api.v1.distribution.get_offset_distribution_cached", AsyncMock(return_value=([], "global"))), \
         patch("app.api.v1.distribution.get_avg_participants", AsyncMock(return_value=0)):
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
