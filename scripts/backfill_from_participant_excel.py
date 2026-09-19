"""
로컬 참여자 Excel 로 과거 적재분을 백필한다 (T-035). 재다운로드 없음.

data/participants/participants_{bidid}.xlsx 16,000여 장에 처음부터 있었는데
버려지던 세 가지를 채운다:

  1. bid_participants.company_id / company_name / ceo_name  (업체 식별자)
  2. bids_history.estimated_price                           (추정가격)
  3. bid_preliminary_prices                                 (복수예가 15개 + 추첨 번호)

597만 행을 ORM 으로 UPDATE 하면 몇 시간이 걸리므로 sqlite3 executemany 로 직접
쓴다. 파싱은 검증된 `app.etl.participant_excel` 을 그대로 쓴다.

실행:
    python scripts/backfill_from_participant_excel.py            # 전체
    python scripts/backfill_from_participant_excel.py --limit 200  # 시험
    python scripts/backfill_from_participant_excel.py --resume     # 이미 업체가 채워진 공고는 건너뜀

몇 번 돌려도 같은 결과다 (company_id IS NULL 인 행만, 없는 (project_id, num) 만).
"""

import argparse
import glob
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.etl.participant_excel import parse_participant_workbook

PART_DIR = Path(__file__).resolve().parent.parent / "data" / "participants"


def _db_path() -> str:
    url = settings.DATABASE_URL
    if "sqlite" not in url:
        sys.exit("이 스크립트는 로컬 SQLite 전용이다. DATABASE_URL 을 확인할 것.")
    return url.split("///", 1)[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", action="store_true", help="업체가 이미 채워진 공고는 파일을 열지 않는다")
    args = ap.parse_args()

    files = sorted(glob.glob(str(PART_DIR / "participants_*.xls*")), key=os.path.getmtime)
    if args.limit:
        files = files[-args.limit:]
    print(f"파일 {len(files)}개")

    con = sqlite3.connect(_db_path(), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    done: set[str] = set()
    if args.resume:
        done = {r[0] for r in con.execute(
            "SELECT DISTINCT project_id FROM bid_participants WHERE company_id IS NOT NULL"
        )}
        print(f"이미 채워진 공고 {len(done)}개 → 건너뜀")

    known_pids = {r[0] for r in con.execute("SELECT project_id FROM bids_history")}

    t0 = time.time()
    n_files = n_rows = n_prelim = n_est = n_skip = n_err = 0
    for i, f in enumerate(files, 1):
        try:
            wb = parse_participant_workbook(f)
        except Exception as e:
            n_err += 1
            print(f"  [!] {Path(f).name}: {type(e).__name__}: {e}")
            continue
        pid = wb.project_id
        if not pid or not wb.rows or pid in done:
            n_skip += 1
            continue

        rows = [
            (r.company_id, r.company_name, r.ceo_name, pid, r.rank)
            for r in wb.rows if r.company_id
        ]
        c = con.executemany(
            "UPDATE bid_participants SET company_id=?, company_name=?, ceo_name=? "
            "WHERE project_id=? AND rank=? AND company_id IS NULL",
            rows,
        )
        n_rows += c.rowcount if c.rowcount is not None and c.rowcount >= 0 else 0

        if pid in known_pids and wb.estimated_price:
            c = con.execute(
                "UPDATE bids_history SET estimated_price=? "
                "WHERE project_id=? AND estimated_price IS NULL",
                (wb.estimated_price, pid),
            )
            n_est += c.rowcount

        if wb.preliminary_prices:
            c = con.executemany(
                "INSERT OR IGNORE INTO bid_preliminary_prices (project_id, num, price, base_pct, is_selected) "
                "VALUES (?, ?, ?, ?, ?)",
                [(pid, p.num, p.price, str(p.base_pct), int(p.is_selected)) for p in wb.preliminary_prices],
            )
            n_prelim += c.rowcount if c.rowcount is not None and c.rowcount >= 0 else 0

        n_files += 1
        if n_files % 200 == 0:
            con.commit()
            el = time.time() - t0
            print(f"  {i}/{len(files)}  업체 {n_rows:,}행  추정가격 {n_est}  복수예가 {n_prelim:,}  {el:.0f}s", flush=True)

    con.commit()
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print(
        f"\n완료: 파일 {n_files} / 건너뜀 {n_skip} / 오류 {n_err}\n"
        f"  업체 컬럼 채운 행: {n_rows:,}\n"
        f"  추정가격 채운 공고: {n_est:,}\n"
        f"  복수예가 삽입: {n_prelim:,}\n"
        f"  {time.time() - t0:.0f}s"
    )


if __name__ == "__main__":
    main()
