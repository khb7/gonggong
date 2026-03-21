"""
app/jobs/scheduler.py
APScheduler 설정 — FastAPI lifespan에서 시작/종료.

매일 COLLECT_HOUR시(KST)에 전날 낙찰결과를 자동 수집한다.
G2B_API_KEY가 없으면 스케줄러를 등록하지 않는다.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


def setup_scheduler() -> None:
    """스케줄러에 잡을 등록한다. use_mock_g2b이면 등록 생략."""
    if settings.use_mock_g2b:
        logger.info("G2B_API_KEY 없음 — 자동 수집 스케줄러 비활성화")
        return

    from app.jobs.collect import run_daily_collect

    if scheduler.get_job("daily_collect"):
        scheduler.remove_job("daily_collect")

    scheduler.add_job(
        run_daily_collect,
        trigger=CronTrigger(hour=settings.COLLECT_HOUR, minute=0),
        id="daily_collect",
        name="일별 낙찰결과 자동 수집",
        misfire_grace_time=3600,   # 서버가 꺼져있다가 켜지면 1시간 내 실행
    )
    logger.info(
        f"자동 수집 스케줄 등록: 매일 {settings.COLLECT_HOUR:02d}:00 (KST)"
    )
