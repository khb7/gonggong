"""
Info21c 참여자 XLS → bid_participants DB 적재.

사용법:
    python scripts/etl_participants.py
    python scripts/etl_participants.py --dir "G:/내 드라이브/gonggong/participants"
    python scripts/etl_participants.py --dry-run   # DB 저장 없이 파싱만 검증

XLS 레이아웃 (공고명 타입):
  공통 헤더:
    행1(0-based row0): 공고명
    행3(row2): 공고번호(col2), 발주기관(col7)
    행5(row4): 예정가격/추정가격(col2), 낙찰하한율(col8)

  데이터 섹션 (구형 7열 / 신형 12열):
    rank=1 시작 행이 데이터 시작
    7열:  rank(0), company_num(1), -(2), company_name(3), -(4), rep(5), bid_amount(6)
    12열: 위에 + bid_rate%(8), base_rate%(9), vs_lower%(10)
"""

import argparse
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncio
import olefile
import xlrd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import BidParticipants

DEFAULT_DIR  = Path("G:/내 드라이브/gonggong/participants")


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

def _open_xls(path: Path):
    """olefile로 OLE 스트림 추출 후 xlrd에 전달 (손상 파일 대응)."""
    ole = olefile.OleFileIO(str(path))
    data = ole.openstream('Workbook').read()
    ole.close()
    return xlrd.open_workbook(file_contents=data)


def parse_xls(path: Path) -> dict | None:
    """
    XLS 파일 파싱. olefile + xlrd 사용 (win32com 대비 ~200배 빠름).
    반환: {project_id, participants: [{rank, bid_amount, bid_rate, base_rate, vs_lower_limit, is_winner}]}
    실패 시 None.
    """
    try:
        wb = _open_xls(path)
    except Exception:
        return None

    try:
        ws = wb.sheet_by_index(0)
        nrows = ws.nrows

        # project_id (0-based: 행2, 열2)
        project_id = str(ws.cell_value(2, 2) or "").strip()
        if not project_id:
            return None

        # 데이터 섹션 찾기: rank=1로 시작하는 마지막 연속 구간
        # col 0이 1.0인 행을 찾고, 그 다음 행이 2.0인지 확인
        data_start = None
        for i in range(nrows - 1):
            v = ws.cell_value(i, 0)
            try:
                if int(float(v)) == 1 and int(float(ws.cell_value(i + 1, 0))) == 2:
                    data_start = i
            except (ValueError, TypeError):
                continue

        if data_start is None:
            return None

        participants = []
        for i in range(data_start, nrows):
            raw_rank = ws.cell_value(i, 0)
            try:
                rank = int(float(raw_rank))
            except (ValueError, TypeError):
                break
            if rank <= 0:
                break

            bid_amount = _clean_money(ws.cell_value(i, 6))
            if bid_amount is None:
                continue

            # 신형(12열)은 투찰율% 있음, 구형(7열)은 None
            bid_rate  = _clean_rate(ws.cell_value(i, 8))
            base_rate = _clean_rate(ws.cell_value(i, 9))
            vs_ll     = _clean_rate(ws.cell_value(i, 10))

            # bid_rate / base_rate: 정상 범위 0.1~9.9 (10%~990%), 벗어나면 None
            if bid_rate is not None and not (Decimal("0.1") <= bid_rate <= Decimal("9.9")):
                bid_rate = None
            if base_rate is not None and not (Decimal("0.1") <= base_rate <= Decimal("9.9")):
                base_rate = None
            # vs_lower_limit: 음수 허용, Numeric(10,6) 오버플로만 방어
            if vs_ll is not None and (vs_ll < Decimal("-99") or vs_ll > Decimal("99")):
                vs_ll = None

            # bid_rate NOT NULL 제약 — 없으면 행 스킵
            if bid_rate is None:
                continue

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


# ── DB 적재 ───────────────────────────────────────────────────────────────────

async def run(xls_dir: Path, dry_run: bool) -> None:
    """앱과 동일한 DB(settings.DATABASE_URL → 기본 sqlite)에 적재한다."""
    files = sorted(xls_dir.glob("*.xls"))
    print(f"XLS 파일: {len(files)}개")

    existing: set[str] = set()

    if not dry_run:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(BidParticipants.project_id).distinct())
            existing = {r[0] for r in result.all()}
        print(f"이미 적재된 project_id: {len(existing)}개")
    else:
        print("DRY-RUN 모드 (DB 저장 없음)")

    ok = skip = fail = 0

    if dry_run:
        for i, f in enumerate(files, 1):
            data = parse_xls(f)
            if data is None:
                fail += 1
                if fail <= 10 or fail % 50 == 0:
                    print(f"[{i}/{len(files)}] FAIL  {f.name}")
                continue
            pid = data["project_id"]
            n = len(data["participants"])
            if pid in existing:
                skip += 1
                continue
            fmt = "7열" if data["participants"][0]["bid_rate"] is None else "12열"
            print(f"[{i}/{len(files)}] OK {fmt}  {pid}  {n}명")
            ok += 1
        print(f"\n완료: 성공={ok}, 스킵={skip}, 실패={fail}")
        return

    async with AsyncSessionLocal() as session:
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

            for p in data["participants"]:
                session.add(BidParticipants(
                    project_id     = pid,
                    rank           = p["rank"],
                    bid_amount     = p["bid_amount"],
                    bid_rate       = p["bid_rate"],
                    base_rate      = p["base_rate"],
                    vs_lower_limit = p["vs_lower_limit"],
                    is_winner      = p["is_winner"],
                ))
            existing.add(pid)
            ok += 1

            if ok % 50 == 0:
                await session.commit()
                print(f"[{i}/{len(files)}] 커밋... 누적 {ok}개 공고")

        await session.commit()

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
