"""
국방부형 project_id 에 개찰 연도를 붙여 재키잉한다 (T-037). 로컬 SQLite 전용.

국방부 공고번호(`LPK0148-1`)는 해마다 재사용돼 다른 해의 다른 공고가 한 project_id 아래
섞여 있었다 (자사 투찰 85건 중 18건, 영향권 1,649 공고 / 131만 참여자 행).
새 규칙은 `app/etl/project_id.py` — `LPK0148-1@2026`.

네 단계를 순서대로 밟는다. 순서가 중요하다:

  A. bids_history / bid_license_types / bid_tags     : pid → pid@year(bid_date)
     (한 번호에 한 공고만 남아 있으므로 그 공고의 개찰 연도로 옮기면 된다)
  B. bid_notices_open / bid_final_awards             : pid → pid@year(open_at)
  C. 목록 Excel 전체 재적재 (data/downloads/info21c_*.xlsx)
     충돌 때문에 "이미 있음" 으로 건너뛰었던 공고가 새 키로 들어온다. 참여자 투찰율
     재계산에 필요한 예정가격·A값이 여기서 채워지므로 D 보다 먼저다.
  D. bid_participants / bid_preliminary_prices 는 **지우고 다시 넣는다**
     행에 개찰일이 없어 섞인 행을 가를 수 없다. 로컬 참여자 Excel
     (data/participants/participants_{bidid}.xls*) 16,000여 장에서 국방부형만 골라 새 키로 넣는다.

기본은 dry-run 이다. 실제 반영은 --apply. 반영 전에 DB 를 복사해 둘 것:
    cp data/gonggong.db data/gonggong.db.bak-rekey
    python scripts/rekey_military_project_ids.py --apply
    python scripts/build_offset_histogram.py          # 사전계산 갱신
    python scripts/validate_data.py
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import settings
from app.engine.a_value import bid_rate_with_a_value
from app.etl.participant_excel import parse_participant_workbook
from app.etl.project_id import canonical_project_id, is_military_notice_no, split_project_id

PART_DIR = ROOT / "data" / "participants"
LIST_DIR = ROOT / "data" / "downloads"
MIL_GLOB = "[A-Z][A-Z][A-Z][0-9][0-9][0-9][0-9]-[0-9]"  # sqlite GLOB: 연도 없는 국방부형


def _db_path() -> str:
    url = settings.DATABASE_URL
    if "sqlite" not in url:
        sys.exit("이 스크립트는 로컬 SQLite 전용이다. DATABASE_URL 을 확인할 것.")
    return url.split("///", 1)[1]


def _year(raw) -> int | None:
    if raw is None:
        return None
    s = str(raw)
    try:
        return datetime.fromisoformat(s[:19]).year
    except ValueError:
        return int(s[:4]) if s[:4].isdigit() else None


# ── A/B: 키만 바꾸면 되는 표 ───────────────────────────────────────────────────

def rekey_table(con: sqlite3.Connection, table: str, date_col: str, apply: bool,
                children: tuple[str, ...] = ()) -> tuple[int, int]:
    """국방부형 pid 행을 pid@year 로 옮긴다. (옮긴 수, 연도 없어 못 옮긴 수)."""
    rows = con.execute(
        f"SELECT project_id, {date_col} FROM {table} WHERE project_id GLOB ?", (MIL_GLOB,)
    ).fetchall()
    moved = skipped = 0
    for pid, d in rows:
        y = _year(d)
        if y is None:
            skipped += 1
            continue
        new = f"{pid}@{y}"
        if apply:
            con.execute(f"UPDATE {table} SET project_id=? WHERE project_id=?", (new, pid))
            for ch in children:
                con.execute(f"UPDATE {ch} SET project_id=? WHERE project_id=?", (new, pid))
        moved += 1
    return moved, skipped


# ── C: 목록 재적재 ─────────────────────────────────────────────────────────────

async def relist(apply: bool) -> int:
    from scripts.etl_csv import extract_and_transform, load_to_db

    files = sorted(glob.glob(str(LIST_DIR / "info21c_*.xls*")))
    print(f"[C] 목록 Excel {len(files)}개")
    if not apply:
        return 0
    inserted_total = 0
    for i, f in enumerate(files, 1):
        df = extract_and_transform(Path(f))
        if df.empty:
            continue
        inserted, _ = await load_to_db(df, upsert=False)
        inserted_total += inserted
        if i % 20 == 0:
            print(f"    {i}/{len(files)}  신규 누적 {inserted_total}", flush=True)
    return inserted_total


# ── D: 참여자 지우고 다시 넣기 ─────────────────────────────────────────────────

def reload_participants(con: sqlite3.Connection, apply: bool) -> dict:
    files = sorted(glob.glob(str(PART_DIR / "participants_*.xls*")), key=os.path.getmtime)
    print(f"[D] 참여자 Excel {len(files)}개 (국방부형만 골라 넣는다)")

    before = con.execute(
        "SELECT COUNT(*) FROM bid_participants WHERE project_id GLOB ?", (MIL_GLOB,)
    ).fetchone()[0]
    if apply:
        con.execute("DELETE FROM bid_participants WHERE project_id GLOB ?", (MIL_GLOB,))
        con.execute("DELETE FROM bid_preliminary_prices WHERE project_id GLOB ?", (MIL_GLOB,))
        con.commit()

    notice = {
        pid: (est or 0, a or 0)
        for pid, est, a in con.execute(
            "SELECT project_id, est_price, a_value FROM bids_history WHERE project_id LIKE '%@%'"
        )
    }

    stat = dict(deleted=before, files=0, notices=0, rows=0, prelim=0, no_year=0, no_notice=0, err=0)
    seen: set[str] = set()
    t0 = time.time()
    for i, f in enumerate(files, 1):
        try:
            wb = parse_participant_workbook(f)
        except Exception as e:  # 깨진 파일은 건너뛰고 센다
            stat["err"] += 1
            print(f"    [!] {Path(f).name}: {type(e).__name__}: {e}")
            continue
        raw, year = split_project_id(wb.project_id)
        if not is_military_notice_no(raw):
            continue
        if year is None:
            stat["no_year"] += 1
            continue
        pid = wb.project_id
        if pid in seen or not wb.rows:
            continue
        seen.add(pid)
        stat["files"] += 1
        est, a = notice.get(pid, (0, 0))
        if pid not in notice:
            stat["no_notice"] += 1
        if not apply:
            stat["rows"] += len(wb.rows)
            stat["prelim"] += len(wb.preliminary_prices)
            continue
        rows = []
        for r in wb.rows:
            rate = bid_rate_with_a_value(r.bid_amount, est, a) if est else None
            rows.append((
                pid, r.rank, r.bid_amount, str(rate if rate is not None else r.bid_rate),
                int(r.rank == 1), r.company_id, r.company_name, r.ceo_name,
            ))
        c = con.executemany(
            "INSERT OR IGNORE INTO bid_participants "
            "(project_id, rank, bid_amount, bid_rate, is_winner, company_id, company_name, ceo_name, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            rows,
        )
        stat["rows"] += c.rowcount if c.rowcount and c.rowcount > 0 else 0
        stat["notices"] += 1
        if wb.preliminary_prices:
            c = con.executemany(
                "INSERT OR IGNORE INTO bid_preliminary_prices (project_id, num, price, base_pct, is_selected) "
                "VALUES (?, ?, ?, ?, ?)",
                [(pid, p.num, p.price, str(p.base_pct), int(p.is_selected)) for p in wb.preliminary_prices],
            )
            stat["prelim"] += c.rowcount if c.rowcount and c.rowcount > 0 else 0
        if stat["notices"] % 200 == 0:
            con.commit()
            print(f"    {i}/{len(files)}  공고 {stat['notices']}  행 {stat['rows']:,}  {time.time() - t0:.0f}s", flush=True)
    con.commit()
    return stat


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 반영한다 (기본은 dry-run)")
    ap.add_argument("--skip-relist", action="store_true", help="C 단계(목록 재적재)를 건너뛴다")
    args = ap.parse_args()
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== 국방부형 project_id 재키잉 [{mode}] ===")

    con = sqlite3.connect(_db_path(), timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")

    m, s = rekey_table(con, "bids_history", "bid_date", args.apply, ("bid_license_types", "bid_tags"))
    print(f"[A] bids_history: 옮김 {m}  연도 없음 {s}")
    m, s = rekey_table(con, "bid_notices_open", "open_at", args.apply)
    print(f"[B] bid_notices_open: 옮김 {m}  연도 없음 {s}")
    m, s = rekey_table(con, "bid_final_awards", "open_date", args.apply)
    print(f"[B] bid_final_awards: 옮김 {m}  연도 없음 {s}")
    con.commit()
    con.close()

    if not args.skip_relist:
        n = asyncio.run(relist(args.apply))
        print(f"[C] 목록 재적재: 신규 {n}건")

    con = sqlite3.connect(_db_path(), timeout=60)
    stat = reload_participants(con, args.apply)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    print(
        f"[D] 참여자: 지운 행 {stat['deleted']:,} / 국방부형 Excel {stat['files']} 장"
        f" → 공고 {stat['notices']} 행 {stat['rows']:,} 복수예가 {stat['prelim']:,}"
        f" / 연도 없음 {stat['no_year']} / bids_history 짝 없음 {stat['no_notice']} / 파일 오류 {stat['err']}"
    )
    if not args.apply:
        print("\ndry-run 이었다. 반영하려면 DB 를 복사한 뒤 --apply.")


if __name__ == "__main__":
    main()
