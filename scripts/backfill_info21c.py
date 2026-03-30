"""
Info21c 과거 데이터 월별 일괄 수집 스크립트.

월 단위로 분할 다운로드 → ETL 적재를 반복한다.
100건/월 초과 시 경고를 출력한다 (현재 페이지 크기 100이 한계).

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


async def process_month(
    start: str,
    end: str,
    license_type: str,
    user_id: str,
    password: str,
) -> dict:
    """한 달치 다운로드 + ETL. 결과 통계 반환."""
    label = f"{start[:4]}-{start[4:6]} {LICENSE_TYPES[license_type]}"

    # ── 다운로드 ─────────────────────────────────────────
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
        print(f"  [{label}] 다운로드 실패: {e}")
        return {"label": label, "downloaded": 0, "inserted": 0, "error": str(e)}

    # ── 파일 행 수 확인 ───────────────────────────────────
    try:
        import pandas as pd
        import xlrd
        suffix = path.suffix.lower()
        if suffix in (".xls", ".xlsx"):
            engine = "xlrd" if suffix == ".xls" else "openpyxl"
            kwargs = {"engine": engine}
            if suffix == ".xls":
                kwargs["engine_kwargs"] = {"ignore_workbook_corruption": True}
            raw_df = pd.read_excel(path, **kwargs)
        else:
            raw_df = pd.read_csv(path, encoding="utf-8-sig", nrows=110)
        raw_count = len(raw_df)
        if raw_count >= 100:
            print(f"  [{label}] ⚠ {raw_count}건 — 페이지 크기(100) 한계 도달. 데이터 누락 가능.")
    except Exception:
        raw_count = -1

    # ── ETL ──────────────────────────────────────────────
    try:
        df = extract_and_transform(path)
        inserted, skipped = await load_to_db(df)
        print(f"  [{label}] 파일 {raw_count}건 → 적재 {inserted}건 / 스킵 {skipped}건")
        return {"label": label, "downloaded": raw_count, "inserted": inserted, "skipped": skipped}
    except Exception as e:
        print(f"  [{label}] ETL 실패: {e}")
        return {"label": label, "downloaded": raw_count, "inserted": 0, "error": str(e)}


async def main():
    parser = argparse.ArgumentParser(description="Info21c 월별 일괄 백필")
    parser.add_argument("--start", type=int, required=True, help="시작 연도 (예: 2023)")
    parser.add_argument("--end",   type=int, required=True, help="종료 연도 (예: 2025)")
    parser.add_argument("--type",  choices=["0002", "0023", "all"], default="all")
    parser.add_argument("--id",    default=DEFAULT_ID)
    parser.add_argument("--pw",    default=DEFAULT_PW)
    args = parser.parse_args()

    types = list(LICENSE_TYPES.keys()) if args.type == "all" else [args.type]
    months = month_ranges(args.start, args.end)

    print(f"=== 백필 시작: {args.start}~{args.end}년, 공종: {[LICENSE_TYPES[t] for t in types]} ===")
    print(f"    총 {len(months) * len(types)}회 다운로드 예정\n")

    total_inserted = 0
    warnings = []

    for license_type in types:
        for start, end in months:
            result = await process_month(start, end, license_type, args.id, args.pw)
            total_inserted += result.get("inserted", 0)
            if result.get("downloaded", 0) >= 100:
                warnings.append(result["label"])
            await asyncio.sleep(2)  # 서버 부하 방지

    print(f"\n=== 완료 ===")
    print(f"총 적재: {total_inserted}건")
    if warnings:
        print(f"\n⚠ 100건 한계 도달 (데이터 누락 가능, 월별 재확인 필요):")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    asyncio.run(main())
