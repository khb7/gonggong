"""
app/api/v1/stats.py
대시보드용 통계 API 엔드포인트.

  GET  /api/v1/stats/overview       — 전체 현황
  GET  /api/v1/stats/clients        — 발주처별 통계
  GET  /api/v1/stats/regions        — 지역별 통계
  GET  /api/v1/stats/distribution   — 사정률 분포 (히스토그램)
  GET  /api/v1/stats/backfill       — 백필 상태 조회
  POST /api/v1/stats/backfill       — 백필 실행 요청
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import BidsHistory
from app.db.session import get_db
from app.engine.statistics import trimmed_median, mad
from app.jobs.backfill_state import state as backfill_state

router = APIRouter()


# ──────────────────────────────────────────────────────────────
# 응답 스키마
# ──────────────────────────────────────────────────────────────

class DateRange(BaseModel):
    start: Optional[str]
    end: Optional[str]


class OverviewResponse(BaseModel):
    total_records: int
    date_range: DateRange
    last_collected: Optional[str]
    by_project_type: dict[str, int]


class ClientStat(BaseModel):
    client_name: str
    record_count: int
    avg_adjustment_rate: float
    avg_participants: float


class RegionStat(BaseModel):
    region: str
    record_count: int
    avg_adjustment_rate: float


class DistributionResponse(BaseModel):
    bins: list[float]        # 구간 중간값 (len = bins_count)
    counts: list[int]
    total: int
    median: float
    mad: float
    min_rate: float
    max_rate: float


class BackfillProgressOut(BaseModel):
    chunk_current: int
    chunk_total: int
    chunk_start: str
    chunk_end: str
    records_so_far: int


class BackfillLastRun(BaseModel):
    started_at: str
    completed_at: Optional[str]
    start_date: str
    end_date: str
    inserted: int
    error: Optional[str]


class BackfillStatusResponse(BaseModel):
    is_running: bool
    progress: Optional[BackfillProgressOut]
    last_run: Optional[BackfillLastRun]


class BackfillTriggerRequest(BaseModel):
    start_date: date
    end_date: date


class BackfillTriggerResponse(BaseModel):
    accepted: bool
    message: str


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def _fmt(d) -> Optional[str]:
    return d.isoformat() if d else None


def _histogram(values: list[float], bins: int) -> DistributionResponse:
    """파이썬 내장으로 히스토그램 계산."""
    if not values:
        return DistributionResponse(
            bins=[], counts=[], total=0,
            median=0.0, mad=0.0,
            min_rate=0.0, max_rate=0.0,
        )

    from decimal import Decimal
    dec_vals = [Decimal(str(v)) for v in values]
    med = float(trimmed_median(dec_vals))
    mad_v = float(mad(dec_vals))

    lo, hi = min(values), max(values)
    total = len(values)

    if lo == hi:
        return DistributionResponse(
            bins=[lo], counts=[total], total=total,
            median=med, mad=mad_v,
            min_rate=lo, max_rate=hi,
        )

    step = (hi - lo) / bins
    # bin centers
    centers = [round(lo + (i + 0.5) * step, 6) for i in range(bins)]
    counts = [0] * bins
    for v in values:
        idx = int((v - lo) / step)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1

    return DistributionResponse(
        bins=centers,
        counts=counts,
        total=total,
        median=round(med, 6),
        mad=round(mad_v, 6),
        min_rate=round(lo, 6),
        max_rate=round(hi, 6),
    )


# ──────────────────────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────────────────────

@router.get("/stats/overview", response_model=OverviewResponse)
async def get_overview(db: AsyncSession = Depends(get_db)):
    """전체 현황: 총 건수, 수집 기간, 공종별 건수."""
    total = (await db.execute(select(func.count()).select_from(BidsHistory))).scalar_one()
    earliest = (await db.execute(select(func.min(BidsHistory.bid_date)))).scalar_one()
    latest   = (await db.execute(select(func.max(BidsHistory.bid_date)))).scalar_one()

    rows = (await db.execute(
        select(BidsHistory.project_type, func.count().label("cnt"))
        .group_by(BidsHistory.project_type)
    )).all()
    by_type = {r.project_type: r.cnt for r in rows}

    return OverviewResponse(
        total_records=total,
        date_range=DateRange(start=_fmt(earliest), end=_fmt(latest)),
        last_collected=_fmt(latest),
        by_project_type=by_type,
    )


@router.get("/stats/clients", response_model=list[ClientStat])
async def get_client_stats(
    limit: int = Query(default=30, ge=1, le=100),
    project_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """발주처별 낙찰 건수 + 평균 사정률 + 평균 참여업체 수 (상위 N개)."""
    q = (
        select(
            BidsHistory.client_name,
            func.count().label("cnt"),
            func.avg(BidsHistory.adjustment_rate).label("avg_rate"),
            func.avg(BidsHistory.participants).label("avg_part"),
        )
        .group_by(BidsHistory.client_name)
        .order_by(func.count().desc())
        .limit(limit)
    )
    if project_type:
        q = q.where(BidsHistory.project_type == project_type)

    rows = (await db.execute(q)).all()
    return [
        ClientStat(
            client_name=r.client_name,
            record_count=r.cnt,
            avg_adjustment_rate=round(float(r.avg_rate), 6),
            avg_participants=round(float(r.avg_part), 1),
        )
        for r in rows
    ]


@router.get("/stats/regions", response_model=list[RegionStat])
async def get_region_stats(
    project_type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """지역별 낙찰 건수 + 평균 사정률."""
    q = (
        select(
            BidsHistory.region,
            func.count().label("cnt"),
            func.avg(BidsHistory.adjustment_rate).label("avg_rate"),
        )
        .group_by(BidsHistory.region)
        .order_by(func.count().desc())
    )
    if project_type:
        q = q.where(BidsHistory.project_type == project_type)

    rows = (await db.execute(q)).all()
    return [
        RegionStat(
            region=r.region,
            record_count=r.cnt,
            avg_adjustment_rate=round(float(r.avg_rate), 6),
        )
        for r in rows
    ]


@router.get("/stats/distribution", response_model=DistributionResponse)
async def get_distribution(
    project_type: Optional[str] = Query(default=None),
    bins: int = Query(default=40, ge=5, le=200),
    db: AsyncSession = Depends(get_db),
):
    """사정률 분포 히스토그램 데이터."""
    q = select(BidsHistory.adjustment_rate)
    if project_type:
        q = q.where(BidsHistory.project_type == project_type)

    rows = (await db.execute(q)).scalars().all()
    values = [float(r) for r in rows]
    return _histogram(values, bins)


# ──────────────────────────────────────────────────────────────
# 백필 상태 / 트리거
# ──────────────────────────────────────────────────────────────

@router.get("/stats/backfill", response_model=BackfillStatusResponse)
async def get_backfill_status():
    """백필 실행 상태 조회."""
    prog = None
    if backfill_state.is_running:
        p = backfill_state.progress
        prog = BackfillProgressOut(
            chunk_current=p.chunk_current,
            chunk_total=p.chunk_total,
            chunk_start=p.chunk_start,
            chunk_end=p.chunk_end,
            records_so_far=p.records_so_far,
        )

    last = None
    if backfill_state.last_run:
        lr = backfill_state.last_run
        last = BackfillLastRun(
            started_at=lr.started_at.isoformat(),
            completed_at=lr.completed_at.isoformat() if lr.completed_at else None,
            start_date=lr.start_date,
            end_date=lr.end_date,
            inserted=lr.inserted,
            error=lr.error,
        )

    return BackfillStatusResponse(
        is_running=backfill_state.is_running,
        progress=prog,
        last_run=last,
    )


async def _run_backfill(start_date: date, end_date: date):
    """백그라운드에서 백필 실행."""
    from app.db.crud import get_collected_dates
    from app.db.crud_write import upsert_bids_history
    from app.db.session import AsyncSessionLocal, engine
    from app.external.g2b_collector import G2BCollector

    backfill_state.start(str(start_date), str(end_date))
    try:
        async with AsyncSessionLocal() as db:
            collected = await get_collected_dates(db, start_date, end_date)

        def on_chunk(chunk_num, total_chunks, c_start, c_end, records_so_far):
            backfill_state.update_chunk(
                current=chunk_num,
                total=total_chunks,
                start=str(c_start),
                end=str(c_end),
                records=records_so_far,
            )

        collector = G2BCollector(api_key=settings.G2B_API_KEY)
        records = await collector.collect_range(
            start_date, end_date,
            skip_dates=collected,
            on_chunk=on_chunk,
        )

        async with AsyncSessionLocal() as db:
            inserted, _ = await upsert_bids_history(db, records)

        await engine.dispose()
        backfill_state.finish(inserted)

    except Exception as e:
        backfill_state.fail(str(e))
        raise


@router.post("/stats/backfill", response_model=BackfillTriggerResponse)
async def trigger_backfill(
    body: BackfillTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """백필 실행 요청. 이미 실행 중이면 409 반환."""
    if backfill_state.is_running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="백필이 이미 실행 중입니다.",
        )
    if settings.use_mock_g2b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="G2B_API_KEY가 설정되지 않아 백필을 실행할 수 없습니다.",
        )
    if body.start_date > body.end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_date가 end_date보다 늦습니다.",
        )

    background_tasks.add_task(_run_backfill, body.start_date, body.end_date)
    return BackfillTriggerResponse(
        accepted=True,
        message=f"{body.start_date} ~ {body.end_date} 백필을 백그라운드에서 시작합니다.",
    )


# ──────────────────────────────────────────────────────────────
# 스케줄러 상태
# ──────────────────────────────────────────────────────────────

class SchedulerStatusResponse(BaseModel):
    enabled: bool
    collect_hour: int
    next_run: Optional[str]


@router.get("/stats/scheduler", response_model=SchedulerStatusResponse)
async def get_scheduler_status():
    """자동 수집 스케줄러 상태 조회."""
    from app.jobs.scheduler import scheduler

    job = scheduler.get_job("daily_collect")
    next_run = None
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()

    return SchedulerStatusResponse(
        enabled=job is not None,
        collect_hour=settings.COLLECT_HOUR,
        next_run=next_run,
    )
