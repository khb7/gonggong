"""
로컬 수집 진입점. info21c 수집의 **두 leg 를 모두** 돈다.

    1. 목록 leg  — 공고 Excel  → bids_history     (collect_notices)
    2. 참여자 leg — 참여자 Excel → bid_participants (info21c_participants.run)

둘 다 돌아야 의미가 있다. 분포 엔진은 두 테이블을 조인해 조회하므로 한쪽만
들어오면 그 공고는 엔진에 존재하지 않는 것과 같다. 2026-05-31 부터 목록 leg 가
빠진 채로 돌아 고아 공고가 쌓였고, 에러가 0건이라 드러나지 않았다.
그래서 실행 끝에 고아 수를 세고, 늘었으면 종료 코드 1 로 알린다.

아직 참여자 데이터가 없는 날짜만 골라 받으므로 여러 번 돌려도 중복되지 않는다.
PC 가 며칠 꺼져 있었어도 다음 실행 때 공백을 함께 메운다.

info21c 는 동시 접속을 막는다. 직접 로그인해 쓰는 중이면 실패한다.

실행:
    python scripts/daily_collect.py --days 14      # 주 1회면 이걸로 충분
    python scripts/daily_collect.py --days 90
    python scripts/daily_collect.py --start 20251224 --end 20260131

이후 순서 (빼먹으면 서버가 참여자 590만 행을 실시간 스캔한다):
    python scripts/build_offset_histogram.py
    python scripts/validate_data.py
    → DB 를 서버로 전송 (docs/deployment.md 4-3절)
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
from scripts.etl_csv import extract_and_transform, load_to_db
from scripts.info21c_downloader import run_download
from scripts.info21c_participants import DEFAULT_ID, DEFAULT_PW, LICENSE_TYPES, run

# 한 번에 넘기는 최대 일수. 길면 브라우저 세션이 버티지 못한다.
MAX_SPAN = 7


async def collect_notices(a, b, code: str, headless: bool) -> None:
    """목록 leg — info21c 목록 Excel → bids_history 적재.

    **참여자 leg 보다 먼저 돌아야 한다.** 두 가지 이유가 있다:

    1. 분포 엔진은 `bid_participants JOIN bids_history` 로 조회한다
       (`crud_distribution.py`). 공고 행이 없으면 참여자가 있어도 조인에서
       떨어져 나가 엔진에 존재하지 않는 것과 같다.
    2. `info21c_participants.update_bid_type_and_method()` 는 공고 행을
       UPDATE 만 한다. `if row:` 가드 때문에 행이 없으면 **조용히** 지나간다.

    이 leg 가 배선돼 있지 않아서 2026-05-31 부터 고아 참여자가 쌓였다.
    참여자만 들어오고 공고는 안 들어오는데 에러가 0건이라 아무도 몰랐다.
    """
    paths = await run_download(
        start_date=a.strftime("%Y%m%d"),
        end_date=b.strftime("%Y%m%d"),
        license_type=code,
        headless=headless,
        debug=False,
        user_id=DEFAULT_ID,
        password=DEFAULT_PW,
    )
    if not paths:
        print("  [목록] 결과 없음")
        return

    # run_download 는 페이지마다 파일을 하나씩 돌려준다. 목록 엑셀 내보내기가
    # 현재 페이지만 내보내므로, 100건이 넘으면 파일이 여러 개다. 전부 적재한다.
    total_new = total_skip = 0
    for path in paths:
        df = extract_and_transform(path)
        new, skipped = await load_to_db(df, upsert=False)
        total_new += new
        total_skip += skipped
    print(f"  [목록] {len(paths)}개 파일 → 신규 {total_new}건 / 기존 {total_skip}건")


async def count_orphans() -> int:
    """bids_history 에 짝이 없는 참여자 공고 수.

    수집이 반쪽만 돌았는지 알려주는 유일한 신호다. 늘어나면 목록 leg 가
    무언가를 놓쳤다는 뜻이므로 종료 코드로 드러낸다.
    """
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        row = await db.execute(text(
            "SELECT COUNT(DISTINCT p.project_id) FROM bid_participants p "
            "WHERE NOT EXISTS (SELECT 1 FROM bids_history b "
            "                  WHERE b.project_id = p.project_id)"
        ))
        return int(row.scalar() or 0)


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

    orphans_before = await count_orphans()
    print(f"고아 공고(수집 전): {orphans_before}건")

    # info21c 는 동시 접속이 안 된다. 반드시 순차 실행.
    for i, (a, b) in enumerate(ranges, 1):
        for code, name in LICENSE_TYPES.items():
            print(f"\n[{i}/{len(ranges)}] {a}~{b} / {name}({code})", flush=True)
            try:
                # 목록 → 참여자 순서를 지킨다 (collect_notices 주석 참고)
                await collect_notices(a, b, code, args.headless)
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

    # ── 고아 검사 ────────────────────────────────────────────────────────────
    # 참여자만 들어오고 공고가 안 들어온 경우를 잡는다. 조용히 넘어가면
    # 몇 달치가 엔진에서 사라진 채로 쌓인다 (실제로 2026-05~08 에 그랬다).
    orphans_after = await count_orphans()
    delta = orphans_after - orphans_before
    print(f"\n고아 공고: {orphans_before} → {orphans_after} ({delta:+d})")
    if delta > 0:
        print(
            f"⚠ 고아가 {delta}건 늘었다. 목록 leg 가 공고를 놓쳤다는 뜻이다.\n"
            f"  같은 구간을 좁혀서 다시 돌리고, 그래도 남으면 목록 페이지네이션을 확인할 것.\n"
            f"  (엑셀 내보내기는 현재 페이지만 내보낸다 — info21c_downloader.goto_next_page)"
        )
        sys.exit(1)

    print("다음 단계: python scripts/build_offset_histogram.py && python scripts/validate_data.py")


if __name__ == "__main__":
    asyncio.run(main_async(_parse_args()))
