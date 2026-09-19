"""
tests/test_api_distribution_open_notice.py
/bid/distribution 이 공고번호로 bid_notices_open 을 먼저 보는지 (T-035).

info21c 개찰 전 공고를 찾으면 G2B 를 부르지 않고 그 값으로 분포를 계산한다.
G2B 단건 조회는 T-016 으로 죽어 있으므로 이 경로가 사실상 자동 조회의 전부다.
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.db.models import BidNoticeOpen
from tests.test_api_distribution import client, _dist, _MOCK_ROWS, _call  # noqa: F401


def _open_notice(**over) -> BidNoticeOpen:
    base = dict(
        project_id="R26BK01737250-001", info21c_bidid="x", notice_title="갈매수변공원",
        client_name="경기도 구리시", demand_org="경기도 구리시", region="경기",
        license_text="조경(식재.시설물)[대],조경식재", contract_method="수의",
        price_method="복수예비가격", preprice_range_pct=3,
        legal_limit_rate=Decimal("0.89745"), a_value=5_904_323, base_price=155_087_000,
        estimated_price=140_988_182, bid_close_at=datetime(2026, 9, 28, 12, 0),
        open_at=datetime(2026, 9, 28, 14, 0),
    )
    base.update(over)
    return BidNoticeOpen(**base)


def test_open_notice_feeds_engine_without_g2b(client):
    fetcher = AsyncMock()
    with _dist(_MOCK_ROWS), \
         patch("app.api.v1.distribution.get_open_notice", AsyncMock(return_value=_open_notice())), \
         patch("app.api.v1.distribution._get_fetcher", return_value=fetcher):
        r = _call(client, {"bid_notice_id": "R26BK01737250-001"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_price"] == 155_087_000
    assert body["lower_limit_rate"] == 0.89745
    assert body["a_value"] == 5_904_323
    assert body["g2b_fetch_status"] == "info21c"
    fetcher.fetch.assert_not_called()


def test_open_notice_without_limit_rate_still_requires_input(client):
    with _dist(_MOCK_ROWS), \
         patch("app.api.v1.distribution.get_open_notice",
               AsyncMock(return_value=_open_notice(legal_limit_rate=None))):
        r = _call(client, {"bid_notice_id": "R26BK01737250-001"})
    assert r.status_code == 400


def test_override_beats_open_notice(client):
    with _dist(_MOCK_ROWS), \
         patch("app.api.v1.distribution.get_open_notice", AsyncMock(return_value=_open_notice())):
        r = _call(client, {
            "bid_notice_id": "R26BK01737250-001",
            "overrides": {"base_price": 100_000_000, "a_value": 0},
        })
    assert r.status_code == 200
    assert r.json()["base_price"] == 100_000_000
    assert r.json()["a_value"] == 0


def test_falls_back_to_g2b_when_not_found(client):
    with _dist(_MOCK_ROWS), \
         patch("app.api.v1.distribution.get_open_notice", AsyncMock(return_value=None)):
        r = _call(client, {"bid_notice_id": "20240540467-03"})
    assert r.status_code == 200
    assert r.json()["g2b_fetch_status"] == "mock"
