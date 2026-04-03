"""
Info21c 과거 데이터 월별 일괄 수집 스크립트.

월 단위로 분할 다운로드 → ETL 적재를 반복한다.
100건/월 도달 시 주(週) 단위로 자동 재분할하여 누락을 최소화한다.

사용법:
  # 2023~2025년 실내건축 + 조경 전체 백필
  python scripts/backfill_info21c.py --start 2023 --end 2025

  # 특정 연도만
  python scripts/backfill_info21c.py --start 2024 --end 2024

  # 특정 공종만
  python scripts/backfill_info21c.py --start 2023 --end 2025 --type 0002
"""

import argparse
import asyncio
import sys
import os
from datetime import date, timedelta
from pathlib import Path
from calendar import monthrange

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.info21c_downloader import run_download, DOWNLOAD_DIR, LICENSE_TYPES
from scripts.etl_csv import extract_and_transform, load_to_db

DEFAULT_ID = os.getenv("INFO21C_ID", "nw8856")
DEFAULT_PW = os.getenv("INFO21C_PW", "nw8856")


def month_ranges(start_year: int, end_year: int):
    """start_year-01 ~ end_year-12 의 월별 (start, end) 리스트 생성."""
    ranges = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            last_day = monthrange(year, month)[1]
            s = f"{year}{month:02d}01"
            e = f"{year}{month:02d}{last_day:02d}"
            ranges.append((s, e))
    return ranges


def week_ranges(year: int, month: int):
    """월 → 주별 (start, end) 리스트 (4~5개 분할)."""
    last_day = monthrange(year, month)[1]
    start = date(year, month, 1)
    end   = date(year, month, last_day)

    ranges = []
    cur = start
    while cur <= end:
        week_end = min(cur + timedelta(days=6), end)
        ranges.append((cur.strftime("%Y%m%d"), week_end.strftime("%Y%m%d")))
        cur = week_end + timedelta(days=1)
    return ranges


def _raw_count(path: Path) -> int:
    """파일의 원시 행 수 반환 (헤더 제외). 읽기 실패 시 -1."""
    try:
        import pandas as pd
        suffix = path.suffix.lower()
        if suffix in (".xls", ".xlsx"):
            engine = "xlrd" if suffix == ".xls" else "openpyxl"
            kwargs = {"engine": engine}
            if suffix == ".xls":
                kwargs["engine_kwargs"] = {"ignore_workbook_corruption": True}
            return len(pd.read_excel(path, **kwargs))
        return len(pd.read_csv(path, encoding="utf-8-sig", nrows=110))
    except Exception:
        return -1


async def _download_and_etl(
    start: str,
    end: str,
    license_type: str,
    user_id: str,
    password: str,
    label: str,
) -> tuple[int, int, int]:
    """다운로드 + ETL. (raw_count, inserted, skipped) 반환. 실패 시 (0, 0, 0)."""
    try:
        path = await run_download(
            start_date=start,
            end_date=end,
            license_type=license_type,
            headless=True,
            debug=False,
            user_id=user_id,
            password=password,
        )
    except Exception as e:
        print(f"    [{label}] 다운로드 실패: {e}")
        return 0, 0, 0

    raw = _raw_count(path)

    try:
        df = extract_and_transform(path)
        ins, skip = await load_to_db(df)
        return raw, ins, skip
    except Exception as e:
        print(f"    [{label}] ETL 실패: {e}")
        return raw, 0, 0


async def process_month(
    start: str,
    end: str,
    license_type: str,
    user_id: str,
    password: str,
) -> dict:
    """
    한 달치 다운로드 + ETL.
    100건 한계 도달 시 주별로 자동 재분할.
    결과 통계 반환.
    """
    year  = int(start[:4])
    month = int(start[4:6])
    label = f"{year}-{month:02d} {LICENSE_TYPES[license_type]}"

    raw, ins, skip = await _download_and_etl(start, end, license_type, user_id, password, label)

    if raw < 100:
        print(f"  [{label}] {raw}건 → 신규 {ins}건 / 스킵 {skip}건")
        return {"label": label, "inserted": ins, "skipped": skip, "split": False}

    # ── 100건 한계 → 주별 재분할 ─────────────────────────
    print(f"  [{label}] {raw}건 한계 도달 → 주별 재분할")
    weeks = week_ranges(year, month)
    total_ins, total_skip = 0, 0

    for w_start, w_end in weeks:
        w_label = f"{label}/{w_start[6:]}~{w_end[6:]}"
        w_raw, w_ins, w_skip = await _download_and_etl(
            w_start, w_end, license_type, user_id, password, w_label
        )
        print(f"    [{w_label}] {w_raw}건 → 신규 {w_ins}건")
        if w_raw >= 100:
            print(f"    [{w_label}] [경고] 주별에서도 100건 한계 - 데이터 누락 가능")
        total_ins  += w_ins
        total_skip += w_skip
        await asyncio.sleep(1)

    print(f"  [{label}] 주별 완료: 신규 {total_ins}건 / 스킵 {total_skip}건")
    return {"label": label, "inserted": total_ins, "skipped": total_skip, "split": True}


async def main():
    parser = argparse.ArgumentParser(description="Info21c 월별 일괄 백필 (100건 시 주별 자동 재분할)")
    parser.add_argument("--start", type=int, required=True, help="시작 연도 (예: 2023)")
    parser.add_argument("--end",   type=int, required=True, help="종료 연도 (예: 2025)")
    parser.add_argument("--type",  choices=["0002", "0023", "all"], default="all")
    parser.add_argument("--id",    default=DEFAULT_ID)
    parser.add_argument("--pw",    default=DEFAULT_PW)
    args = parser.parse_args()

    types  = list(LICENSE_TYPES.keys()) if args.type == "all" else [args.type]
    months = month_ranges(args.start, args.end)

    print(f"=== 백필 시작: {args.start}~{args.end}년, 공종: {[LICENSE_TYPES[t] for t in types]} ===")
    print(f"    총 {len(months) * len(types)}회 다운로드 예정 (100건 달성 시 주별 추가 분할)\n")

    total_inserted = 0
    split_months   = []

    for license_type in types:
        for start, end in months:
            result = await process_month(start, end, license_type, args.id, args.pw)
            total_inserted += result.get("inserted", 0)
            if result.get("split"):
                split_months.append(result["label"])
            await asyncio.sleep(2)

    print(f"\n=== 완료 ===")
    print(f"총 적재: {total_inserted}건")
    if split_months:
        print(f"\n주별 재분할 실행된 월 ({len(split_months)}건):")
        for m in split_months:
            print(f"  - {m}")


if __name__ == "__main__":
    asyncio.run(main())
