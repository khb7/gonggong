"""
초기 과거 데이터 백필 스크립트.

사용법:
  python scripts/backfill.py --start 20250101 --end 20260101

⚠ 1년치 약 50,000~150,000건, API 호출 수만~수십만 회 예상.
  G2B_API_KEY가 .env에 설정되어 있어야 한다.
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.jobs.collect import collect_range


async def main():
    parser = argparse.ArgumentParser(description="나라장터 낙찰결과 백필")
    parser.add_argument("--start", required=True, help="수집 시작일 (YYYYMMDD)")
    parser.add_argument("--end",   required=True, help="수집 종료일 (YYYYMMDD)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y%m%d").date()
    end   = datetime.strptime(args.end,   "%Y%m%d").date()

    print(f"백필 시작: {start} ~ {end}")
    inserted = await collect_range(start, end)
    print(f"완료: 총 {inserted}건 신규 적재")


if __name__ == "__main__":
    # Windows asyncpg 소켓 정리 시 발생하는 WinError 64 억제
    import warnings
    warnings.filterwarnings("ignore")

    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(main())
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
