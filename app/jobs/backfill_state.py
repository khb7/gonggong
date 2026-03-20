"""
app/jobs/backfill_state.py
백필 실행 상태 추적 (in-memory).
FastAPI 프로세스 내에서만 유효.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BackfillProgress:
    chunk_current: int = 0
    chunk_total: int = 0
    chunk_start: str = ""
    chunk_end: str = ""
    records_so_far: int = 0


@dataclass
class BackfillRun:
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    start_date: str = ""
    end_date: str = ""
    inserted: int = 0
    error: Optional[str] = None


class BackfillState:
    def __init__(self):
        self.is_running: bool = False
        self.progress: BackfillProgress = BackfillProgress()
        self.last_run: Optional[BackfillRun] = None

    def start(self, start_date: str, end_date: str):
        self.is_running = True
        self.progress = BackfillProgress()
        self.last_run = BackfillRun(start_date=start_date, end_date=end_date)

    def update_chunk(self, current: int, total: int, start: str, end: str, records: int):
        self.progress.chunk_current = current
        self.progress.chunk_total = total
        self.progress.chunk_start = start
        self.progress.chunk_end = end
        self.progress.records_so_far = records

    def finish(self, inserted: int):
        self.is_running = False
        if self.last_run:
            self.last_run.completed_at = datetime.now()
            self.last_run.inserted = inserted

    def fail(self, error: str):
        self.is_running = False
        if self.last_run:
            self.last_run.completed_at = datetime.now()
            self.last_run.error = error


# 싱글턴 — import해서 공유
state = BackfillState()
