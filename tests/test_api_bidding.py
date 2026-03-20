"""
tests/test_api_bidding.py
POST /api/v1/bid/calculate 엔드포인트 통합 테스트.

DB 의존성은 AsyncMock으로 대체하고,
G2BFetcher는 MockG2BFetcher가 기본으로 사용됨 (G2B_API_KEY 없음).
fallback은 데이터 없음 → 기본값(predicted_rate=1.0) 경로를 테스트.
"""

import pytest
from decimal import Decimal
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db
from app.external.g2b_fetcher import MockG2BFetcher


# ──────────────────────────────────────────
# DB 의존성 Override (DB 없이 실행)
# ──────────────────────────────────────────

async def _mock_db():
    """빈 AsyncSession Mock을 yield."""
    yield AsyncMock()


app.dependency_overrides[get_db] = _mock_db


@pytest.fixture
def client():
    # 실제 API 키가 .env에 있어도 테스트에서는 항상 MockG2BFetcher + mock 상태로 실행
    mock_settings = type("MockSettings", (), {"use_mock_g2b": True, "G2B_API_KEY": ""})()
    with patch("app.api.v1.bidding._get_fetcher", return_value=MockG2BFetcher()),          patch("app.api.v1.bidding.settings", mock_settings),          TestClient(app) as c:
        yield c


# ──────────────────────────────────────────
# 헬스체크
# ──────────────────────────────────────────

def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ──────────────────────────────────────────
# Auto-Fetch Mode (Mock Fetcher + 데이터 없음)
# ──────────────────────────────────────────

def test_calculate_auto_mode_returns_200(client):
    """Auto-Fetch Mode — Mock 데이터로 200 반환 및 응답 구조 검증."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={"bid_notice_id": "TEST-001"},
        )
    assert resp.status_code == 200
    data = resp.json()

    # 응답 필드 존재 여부
    assert "bid_notice_id" in data
    assert "mode" in data
    assert "strategy" in data
    assert "bids" in data
    assert "fallback_level" in data
    assert "predicted_rate" in data


def test_calculate_auto_mode_correct_notice_data(client):
    """TEST-001 공고의 기초금액·기관명이 fetched에 정확히 담겨야 한다."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={"bid_notice_id": "TEST-001"},
        )
    data = resp.json()
    assert data["fetched"]["base_price"] == 1_000_000_000
    assert data["fetched"]["client_name"] == "서울특별시"
    assert data["mode"] == "auto"


def test_calculate_auto_mode_returns_3_bids(client):
    """기본값으로 3개의 타점이 반환되어야 한다."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={"bid_notice_id": "TEST-001"},
        )
    bids = resp.json()["bids"]
    assert len(bids) == 3
    for bid in bids:
        assert "label" in bid
        assert "rate_pct" in bid
        assert "price_krw" in bid
        assert "digit_filter_applied" in bid


def test_calculate_auto_mode_default_fallback(client):
    """데이터 없으면 fallback_level이 'default'이어야 한다."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={"bid_notice_id": "TEST-001"},
        )
    assert resp.json()["fallback_level"] == "default"


# ──────────────────────────────────────────
# Override Mode
# ──────────────────────────────────────────

def test_calculate_override_base_price(client):
    """base_price Override 시 fetched는 원본, 계산은 Override 값으로."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={
                "bid_notice_id": "TEST-001",
                "overrides": {"base_price": 500_000_000},
            },
        )
    data = resp.json()
    assert data["mode"] == "override"
    assert "base_price" in data["overridden_fields"]
    # fetched는 원본(1,000,000,000), 계산에는 500,000,000 반영
    assert data["fetched"]["base_price"] == 1_000_000_000
    # Override된 기초금액 기준 가격이 반영되어야 함
    for bid in data["bids"]:
        assert bid["price_krw"] < 1_000_000_000


def test_calculate_override_mode_label(client):
    """Override Mode에서 mode 필드는 'override'여야 한다."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={
                "bid_notice_id": "TEST-001",
                "overrides": {"participants": 400},
            },
        )
    data = resp.json()
    assert data["mode"] == "override"
    assert data["strategy"] == "aggressive"   # 400명 → Aggressive


def test_calculate_missing_bid_notice_id_returns_422(client):
    """bid_notice_id 없이 요청하면 422 Unprocessable Entity 반환."""
    resp = client.post("/api/v1/bid/calculate", json={})
    assert resp.status_code == 422


def test_calculate_g2b_fetch_status_is_mock(client):
    """API 키 없으면(Mock 사용) g2b_fetch_status가 'mock'이어야 한다."""
    with patch("app.data.fallback.get_rates_by_client", return_value=[]), \
         patch("app.data.fallback.get_rates_by_region", return_value=[]), \
         patch("app.data.fallback.get_rates_by_type_and_bucket", return_value=[]), \
         patch("app.data.fallback.get_all_rates", return_value=[]):

        resp = client.post(
            "/api/v1/bid/calculate",
            json={"bid_notice_id": "TEST-001"},
        )
    assert resp.json()["g2b_fetch_status"] == "mock"
