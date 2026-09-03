"""
로컬 일별 수집 진입점 (Windows 작업 스케줄러용).

아직 참여자 데이터가 들어오지 않은 날짜만 골라 info21c 에서 받아온다.
PC 가 며칠 꺼져 있었어도 다음 실행 때 공백을 함께 메운다.

작업 스케줄러 설정은 docs/deployment.md 참조.

수동 실행:
    python scripts/daily_collect.py                # 최근 30일 중 빈 날짜
    python scripts/daily_collect.py --days 90      # 최근 90일
    python scripts/daily_collect.py --start 20251224 --end 20260131
"""

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.crud import get_participant_collected_dates
from app.db.session import AsyncSessionLocal, engine
from app.jobs.collect_window import pending_ranges
from scripts.info21c_participants import DEFAULT_ID, DEFAULT_PW, LICENSE_TYPES, run

# 한 번에 넘기는 최대 일수. 길면 브라우저 세션이 버티지 못한다.
MAX_SPAN = 7


def _parse_args():
    p = argparse.ArgumentParser(description="info21c 일별 참여자 수집")
    p.add_argument("--days", type=int, default=30, help="오늘로부터 며칠 전까지 볼지 (기본 30)")
    p.add_argument("--start", help="시작일 YYYYMMDD (--days 대신)")
    p.add_argument("--end", help="종료일 YYYYMMDD (--days 대신)")
    p.add_argument("--headless", action="store_true", help="브라우저 창 숨김")
    return p.parse_args()


def _window(args) -> tuple[date, date]:
    if args.start and args.end:
        return (
            datetime.strptime(args.start, "%Y%m%d").date(),
            datetime.strptime(args.end, "%Y%m%d").date(),
        )
    end = date.today() - timedelta(days=1)   # 어제까지. 오늘은 개찰이 안 끝났다
    return end - timedelta(days=args.days - 1), end


async def main_async(args) -> None:
    start, end = _window(args)
    print(f"조회 구간: {start} ~ {end}")

    async with AsyncSessionLocal() as db:
        collected = await get_participant_collected_dates(db, start, end)
    await engine.dispose()

    ranges = pending_ranges(collected, start, end, max_span=MAX_SPAN)
    if not ranges:
        print("빈 날짜 없음. 수집할 것이 없다.")
        return

    total_days = sum((b - a).days + 1 for a, b in ranges)
    print(f"미수집 {total_days}일, {len(ranges)}개 구간")

    # info21c 는 동시 접속이 안 된다. 반드시 순차 실행.
    for i, (a, b) in enumerate(ranges, 1):
        for code, name in LICENSE_TYPES.items():
            print(f"\n[{i}/{len(ranges)}] {a}~{b} / {name}({code})", flush=True)
            try:
                await run(
                    start_date=a.strftime("%Y%m%d"),
                    end_date=b.strftime("%Y%m%d"),
                    license_type=code,
                    user_id=DEFAULT_ID,
                    password=DEFAULT_PW,
                    headless=args.headless,
                )
            except Exception as e:
                # 한 구간이 실패해도 나머지는 계속한다. 놓친 날짜는 다음 실행에서
                # 다시 미수집으로 잡히므로 따라잡힌다.
                print(f"  실패: {type(e).__name__}: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main_async(_parse_args()))
