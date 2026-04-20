"""
Info21c 참여자 XLS → bid_participants DB 적재.

사용법:
    python scripts/etl_participants.py
    python scripts/etl_participants.py --dir "G:/내 드라이브/gonggong/participants"
    python scripts/etl_participants.py --dry-run   # DB 저장 없이 파싱만 검증

XLS 레이아웃 (공고명 타입):
  공통 헤더:
    행1: 공고명
    행3: 공고번호(col3), 발주기관(col8)   [COM 1-based]
    행5: 예정가격/추정가격(col3), 낙찰하한율(col9)

  데이터 섹션 (구형 7열 / 신형 12열):
    '순위' 헤더 다음 행부터 rank가 숫자인 행이 참여자 데이터
    7열: rank(1), company_num(2), -(3), company_name(4), -(5), rep(6), bid_amount(7)
    12열: 위에 + bid_rate%(9), base_rate%(10), vs_lower%(11)
"""

import argparse
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncpg
import asyncio

DATABASE_URL = "postgresql://postgres@localhost:5432/gonggong"
DEFAULT_DIR  = Path("G:/내 드라이브/gonggong/participants")


# ── 단일 Excel 인스턴스 (파일마다 열고 닫지 않음) ─────────────────────────────

_xl = None

def get_xl():
    global _xl
    if _xl is None:
        import win32com.client
        _xl = win32com.client.Dispatch("Excel.Application")
        _xl.Visible = False
        _xl.DisplayAlerts = False
    return _xl

def quit_xl():
    global _xl
    if _xl is not None:
        try:
            _xl.Quit()
        except Exception:
            pass
        _xl = None


# ── 변환 헬퍼 ─────────────────────────────────────────────────────────────────

def _clean_money(val) -> int | None:
    """'723,785,000 (...)' 또는 float → int (원)"""
    if val is None or val == "":
        return None
    s = str(val).split("(")[0].strip().replace(",", "").replace("원", "").replace("₩", "").strip()
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _clean_rate(val) -> Decimal | None:
    """99.5235 또는 '99.5235%' → Decimal 0.995235 (소수 표현, /100)"""
    if val is None or val == "":
        return None
    s = str(val).replace("%", "").strip()
    m = re.match(r"[-\d.]+", s)
    if not m:
        return None
    try:
        return Decimal(m.group()) / 100
    except InvalidOperation:
        return None


# ── XLS 파싱 ──────────────────────────────────────────────────────────────────

def parse_xls(path: Path) -> dict | None:
    """
    XLS 파일 파싱. win32com(Excel COM) 사용.
    반환: {project_id, participants: [{rank, bid_amount, bid_rate, base_rate, vs_lower_limit, is_winner}]}
    실패 시 None.
    """
    xl = get_xl()
    try:
        wb = xl.Workbooks.Open(str(path.absolute()))
    except Exception:
        return None

    try:
        ws = wb.Worksheets(1)
        nrows = ws.UsedRange.Rows.Count
        ncols = ws.UsedRange.Columns.Count

        # 레이아웃 확인
        layout = ws.Cells(1, 1).Value
        if layout != "공고명":
            return None

        # project_id (COM 1-based: 행3, 열3)
        project_id = str(ws.Cells(3, 3).Value or "").strip()
        if not project_id:
            return None

        # 데이터 섹션 찾기: 마지막 '순위' 헤더 다음 행부터
        last_header_row = None
        for i in range(1, nrows + 1):
            if ws.Cells(i, 1).Value == "순위":
                last_header_row = i

        if last_header_row is None:
            return None

        data_start = last_header_row + 1

        participants = []
        for i in range(data_start, nrows + 1):
            # rank: col1이 양수 정수인 행만
            raw_rank = ws.Cells(i, 1).Value
            try:
                rank = int(float(raw_rank))
            except (ValueError, TypeError):
                continue
            if rank <= 0:
                continue

            bid_amount = _clean_money(ws.Cells(i, 7).Value)
            if bid_amount is None:
                continue

            # 신형(12열)은 투찰율% 있음, 구형(7열)은 None
            bid_rate  = _clean_rate(ws.Cells(i, 9).Value)
            base_rate = _clean_rate(ws.Cells(i, 10).Value)
            vs_ll     = _clean_rate(ws.Cells(i, 11).Value)

            participants.append({
                "rank":           rank,
                "bid_amount":     bid_amount,
                "bid_rate":       bid_rate,
                "base_rate":      base_rate,
                "vs_lower_limit": vs_ll,
                "is_winner":      rank == 1,
            })

        if not participants:
            return None

        return {"project_id": project_id, "participants": participants}

    except Exception:
        return None
    finally:
        try:
            wb.Close(False)
        except Exception:
            pass


# ── DB 적재 ───────────────────────────────────────────────────────────────────

INSERT_SQL = """
INSERT INTO bid_participants
    (project_id, rank, bid_amount, bid_rate, base_rate, vs_lower_limit, is_winner)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (project_id, rank) DO NOTHING
"""


async def run(xls_dir: Path, dry_run: bool) -> None:
    files = sorted(xls_dir.glob("*.xls"))
    print(f"XLS 파일: {len(files)}개")

    conn = None
    existing: set[str] = set()

    if not dry_run:
        conn = await asyncpg.connect(DATABASE_URL)
        existing = set(
            r[0] for r in await conn.fetch("SELECT DISTINCT project_id FROM bid_participants")
        )
        print(f"이미 적재된 project_id: {len(existing)}개")
    else:
        print("DRY-RUN 모드 (DB 저장 없음)")

    ok = skip = fail = 0

    try:
        for i, f in enumerate(files, 1):
            data = parse_xls(f)

            if data is None:
                fail += 1
                if fail <= 10 or fail % 50 == 0:
                    print(f"[{i}/{len(files)}] FAIL  {f.name}")
                continue

            pid = data["project_id"]
            n   = len(data["participants"])

            if pid in existing:
                skip += 1
                continue

            if dry_run:
                fmt = "7열" if data["participants"][0]["bid_rate"] is None else "12열"
                print(f"[{i}/{len(files)}] OK {fmt}  {pid}  {n}명")
                ok += 1
            else:
                rows = [
                    (pid, p["rank"], p["bid_amount"], p["bid_rate"],
                     p["base_rate"], p["vs_lower_limit"], p["is_winner"])
                    for p in data["participants"]
                ]
                await conn.executemany(INSERT_SQL, rows)
                existing.add(pid)
                ok += 1
                if ok <= 20 or ok % 50 == 0:
                    fmt = "7열" if data["participants"][0]["bid_rate"] is None else "12열"
                    print(f"[{i}/{len(files)}] OK {fmt}  {pid}  {n}명")

    finally:
        quit_xl()
        if conn:
            await conn.close()

    print(f"\n완료: 성공={ok}, 스킵={skip}, 실패={fail}")
    print(f"bid_participants 총 적재: {ok}개 공고")


def main():
    parser = argparse.ArgumentParser(description="Info21c 참여자 XLS → DB 적재")
    parser.add_argument("--dir",     default=str(DEFAULT_DIR), help="XLS 디렉토리")
    parser.add_argument("--dry-run", action="store_true",      help="파싱만, DB 저장 안 함")
    args = parser.parse_args()

    asyncio.run(run(Path(args.dir), args.dry_run))


if __name__ == "__main__":
    main()
