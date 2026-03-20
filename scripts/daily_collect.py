"""
일별 자동 수집 스크립트 (Windows 작업 스케줄러용).

Windows 작업 스케줄러 설정:
  - 프로그램: python
  - 인수: C:\Users\Lenovo\gonggong\scripts\daily_collect.py
  - 트리거: 매일 02:00
  - 실행 위치: C:\Users\Lenovo\gonggong
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.jobs.collect import run_daily_collect

if __name__ == "__main__":
    asyncio.run(run_daily_collect())
