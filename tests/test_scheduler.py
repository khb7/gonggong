"""
tests/test_scheduler.py
스케줄러 설정 및 /api/v1/stats/scheduler 엔드포인트 테스트.
"""

import pytest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.db.session import get_db


# ──────────────────────────────────────────
# 공통 픽스처
# ──────────────────────────────────────────

async def _mock_db():
    yield AsyncMock()


app.dependency_overrides[get_db] = _mock_db


@pytest.fixture(autouse=True)
def reset_scheduler():
    """각 테스트 전후로 스케줄러를 깨끗한 상태로 초기화."""
    from app.jobs.scheduler import scheduler
    # 이전 테스트에서 등록된 잡 제거
    if scheduler.get_job("daily_collect"):
        scheduler.remove_job("daily_collect")
    yield
    if scheduler.get_job("daily_collect"):
        scheduler.remove_job("daily_collect")


# ──────────────────────────────────────────
# setup_scheduler() 단위 테스트
# ──────────────────────────────────────────

def test_setup_scheduler_registers_job_when_api_key_set():
    """G2B_API_KEY가 있으면 daily_collect 잡이 등록되어야 한다."""
    from app.jobs.scheduler import scheduler, setup_scheduler

    mock_settings = type("S", (), {"use_mock_g2b": False, "COLLECT_HOUR": 3})()
    with patch("app.jobs.scheduler.settings", mock_settings):
        setup_scheduler()

    job = scheduler.get_job("daily_collect")
    assert job is not None, "daily_collect 잡이 등록되지 않음"


def test_setup_scheduler_skips_when_mock_mode():
    """G2B_API_KEY가 없으면 잡이 등록되지 않아야 한다."""
    from app.jobs.scheduler import scheduler, setup_scheduler

    mock_settings = type("S", (), {"use_mock_g2b": True, "COLLECT_HOUR": 3})()
    with patch("app.jobs.scheduler.settings", mock_settings):
        setup_scheduler()

    job = scheduler.get_job("daily_collect")
    assert job is None, "Mock 모드에서 잡이 등록됨"


def test_setup_scheduler_uses_correct_hour():
    """COLLECT_HOUR 설정이 cron trigger에 반영되어야 한다."""
    from app.jobs.scheduler import scheduler, setup_scheduler
    from apscheduler.triggers.cron import CronTrigger

    mock_settings = type("S", (), {"use_mock_g2b": False, "COLLECT_HOUR": 5})()
    with patch("app.jobs.scheduler.settings", mock_settings):
        setup_scheduler()

    job = scheduler.get_job("daily_collect")
    assert job is not None
    trigger = job.trigger
    assert isinstance(trigger, CronTrigger)
    # CronTrigger의 필드 중 hour 확인
    hour_field = next(f for f in trigger.fields if f.name == "hour")
    assert str(hour_field) == "5"


def test_setup_scheduler_replace_existing():
    """setup_scheduler를 두 번 호출해도 잡이 중복 등록되지 않아야 한다."""
    from app.jobs.scheduler import scheduler, setup_scheduler

    mock_settings = type("S", (), {"use_mock_g2b": False, "COLLECT_HOUR": 3})()
    with patch("app.jobs.scheduler.settings", mock_settings):
        setup_scheduler()
        setup_scheduler()

    jobs = [j for j in scheduler.get_jobs() if j.id == "daily_collect"]
    assert len(jobs) == 1, f"잡이 {len(jobs)}개 등록됨 (1개여야 함)"


# ──────────────────────────────────────────
# GET /api/v1/stats/scheduler 엔드포인트 테스트
# ──────────────────────────────────────────

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_scheduler_endpoint_disabled_when_mock():
    """Mock 모드에서 scheduler 엔드포인트는 enabled=False를 반환해야 한다."""
    mock_settings = type("S", (), {"use_mock_g2b": True, "COLLECT_HOUR": 3})()
    with patch("app.jobs.scheduler.settings", mock_settings), \
         TestClient(app) as c:
        resp = c.get("/api/v1/stats/scheduler")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["next_run"] is None


def test_scheduler_endpoint_enabled_with_job():
    """잡이 등록+실행된 상태에서 enabled=True, next_run이 있어야 한다.
    TestClient lifespan 안에서 settings를 패치하여 잡이 등록되게 한다."""
    mock_settings = type("S", (), {"use_mock_g2b": False, "COLLECT_HOUR": 3})()
    with patch("app.jobs.scheduler.settings", mock_settings), \
         TestClient(app) as c:
        resp = c.get("/api/v1/stats/scheduler")

    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["collect_hour"] == 3
    assert data["next_run"] is not None


def test_scheduler_endpoint_returns_correct_hour(client):
    """collect_hour 값이 설정값과 일치해야 한다."""
    mock_settings = type("S", (), {"use_mock_g2b": True, "COLLECT_HOUR": 7})()
    with patch("app.api.v1.stats.settings", mock_settings):
        resp = client.get("/api/v1/stats/scheduler")
    assert resp.status_code == 200
    assert resp.json()["collect_hour"] == 7
