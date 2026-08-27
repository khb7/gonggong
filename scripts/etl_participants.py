"""
Info21c 참여자 XLS → bid_participants DB 적재.

사용법:
    python scripts/etl_participants.py
    python scripts/etl_participants.py --dir "G:/내 드라이브/gonggong/participants"
    python scripts/etl_participants.py --dry-run   # DB 저장 없이 파싱만 검증

XLS 레이아웃 (공고명 타입):
  공통 헤더 (라벨 위치가 파일마다 달라 라벨 문자열로 찾는다):
    공고번호 / 기초금액 / 예정가격 / 낙찰하한율 / 낙찰하한가
    예정가격 셀에는 A값이 "48,361,508,925 (A값: 12,345)" 형태로 함께 들어온다.

  데이터 섹션 (구형 7열 / 신형 12열):
    rank=1 시작 행이 데이터 시작
    7열:  rank(0), company_num(1), -(2), company_name(3), -(4), rep(5), bid_amount(6)
    12열: 위에 + bid_rate%(8), base_rate%(9), vs_lower%(10)
"""

import argparse
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import asyncio
import olefile
import xlrd

sys.path.append(str(Path(__file__).resolve().parent.parent))
from sqlalchemy import select, text

from app.db.models import BidParticipants, BidsHistory
from app.db.session import AsyncSessionLocal
from app.engine.a_value import split_limit_rates

# DB 는 앱과 같은 곳을 본다 (settings.DATABASE_URL). 여기서 postgres URL 을
# 하드코딩하면 적재한 데이터를 엔진이 못 보는 상태가 된다.
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


_HEADER_MAX_ROW = 12


def _cell_after(ws, label: str) -> str:
    """
    헤더 영역에서 label 셀을 찾아 오른쪽의 첫 비어있지 않은 값을 반환한다.

    레이아웃이 파일마다 달라 (row, col) 고정 인덱스로는 못 잡는다.
    """
    for r in range(min(_HEADER_MAX_ROW, ws.nrows)):
        for c in range(ws.ncols):
            if str(ws.cell_value(r, c)).strip() == label:
                for k in range(c + 1, min(c + 4, ws.ncols)):
                    v = str(ws.cell_value(r, k)).strip()
                    if v not in ("", "-"):
                        return v
    return ""


def _first_amount(raw) -> int | None:
    """'48,834,594,000 (순공사원가 ...)' → 48834594000"""
    m = re.search(r"[\d,]+", str(raw))
    if not m:
        return None
    try:
        return int(m.group().replace(",", ""))
    except ValueError:
        return None


def _declared_a_value(raw) -> int | None:
    """예정가격 셀에 붙어오는 '(A값: 12,345)' 파싱. 없으면 None."""
    m = re.search(r"A\s*값\s*[:：]?\s*([\d,]+)", str(raw))
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_notice(ws) -> dict:
    """
    공고 헤더에서 하한율 계산에 필요한 값을 뽑는다.

    낙찰하한율/낙찰하한가는 원본이 제공하는 authoritative 값이다.
    이 값이 bids_history 로 전달되지 않아 과거 적재분의 하한율이
    0.87745 하드코딩으로 오염됐다 (md/design/bid_rate_definitions.md 4절).
    """
    est_raw = _cell_after(ws, "예정가격")
    return {
        "base_price":        _first_amount(_cell_after(ws, "기초금액")),
        "expected_price":    _first_amount(est_raw),
        "lower_limit_price": _first_amount(_cell_after(ws, "낙찰하한가")),
        "declared_rate":     _clean_rate(_cell_after(ws, "낙찰하한율")),
        "declared_a_value":  _declared_a_value(est_raw),
    }


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

        return {
            "project_id": project_id,
            "participants": participants,
            "notice": parse_notice(ws),
        }

    except Exception:
        return None


# ── DB 적재 ───────────────────────────────────────────────────────────────────

# 이름 있는 바인드 파라미터를 쓴다 — sqlite/postgres 양쪽에서 같은 SQL 이 돈다.
INSERT_SQL = text("""
INSERT INTO bid_participants
    (project_id, rank, bid_amount, bid_rate, base_rate, vs_lower_limit, is_winner)
VALUES (:project_id, :rank, :bid_amount, :bid_rate, :base_rate, :vs_lower_limit, :is_winner)
ON CONFLICT (project_id, rank) DO NOTHING
""")


UPDATE_LIMITS_SQL = text("""
UPDATE bids_history SET
    legal_limit_rate     = :legal,
    effective_limit_rate = :effective,
    lower_limit_rate     = COALESCE(:legal, lower_limit_rate),
    a_value              = :a_value,
    has_a_value          = (:a_value > 0)
WHERE project_id = :project_id
""")


def resolve_limits(notice: dict) -> tuple[Decimal | None, Decimal | None, int] | None:
    """
    공고 헤더에서 (법정 하한율, 실효 하한율, A값)을 계산한다.

    원본의 낙찰하한율/낙찰하한가가 authoritative 소스다.
    둘 다 없으면 판별 불가 → None (기존 값을 건드리지 않는다).
    """
    est = notice.get("expected_price")
    llh = notice.get("lower_limit_price")
    declared = notice.get("declared_rate")
    if not est or (not llh and declared is None):
        return None
    return split_limit_rates(est, llh, declared)


async def update_notice_limits(session, dry_run: bool, pending: list[tuple[str, dict]]) -> None:
    """파싱한 공고 헤더로 bids_history 하한율 계열 컬럼을 갱신한다."""
    known = set()
    if session is not None:
        result = await session.execute(select(BidsHistory.project_id))
        known = {r[0] for r in result.all()}

    updated = skipped = unresolved = mismatch = 0
    rows = []

    for pid, notice in pending:
        limits = resolve_limits(notice)
        if limits is None:
            unresolved += 1
            continue
        legal, eff, a_val = limits

        # 원본이 A값을 직접 선언한 경우 역산값과 대조한다 (정합성 확인용).
        declared_a = notice.get("declared_a_value")
        if declared_a is not None and abs(a_val - declared_a) > max(1000, declared_a * 0.001):
            mismatch += 1
            print(f"  A값 불일치  {pid}: 선언={declared_a:,} 역산={a_val:,}")

        if session is not None and pid not in known:
            skipped += 1
            continue

        rows.append({"project_id": pid, "legal": legal, "effective": eff, "a_value": a_val})
        updated += 1

    print()
    print(
        f"[하한율 갱신] 대상={updated} / 판별불가={unresolved} "
        f"/ bids_history에 없음={skipped} / A값 불일치={mismatch}"
    )

    if dry_run or session is None:
        print("  DRY-RUN — DB 갱신 안 함")
        for r in rows[:5]:
            print(f"    {r['project_id']}: 법정={r['legal']} 실효={r['effective']} A={r['a_value']:,}")
        return

    if rows:
        await session.execute(UPDATE_LIMITS_SQL, rows)
        await session.commit()
    print(f"  {len(rows)}건 갱신 완료")


async def run(xls_dir: Path, dry_run: bool, update_limits: bool = False) -> None:
    """앱과 같은 DB(settings.DATABASE_URL)에 적재한다."""
    files = sorted(xls_dir.glob("*.xls"))
    print(f"XLS 파일: {len(files)}개")

    if dry_run:
        print("DRY-RUN 모드 (DB 저장 없음)")
        ok, skip, fail, notices = await _scan(files, existing=set(), session=None)
        _report(ok, skip, fail)
        if update_limits:
            await update_notice_limits(None, True, notices)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BidParticipants.project_id).distinct())
        existing = {r[0] for r in result.all()}
        print(f"이미 적재된 project_id: {len(existing)}개")

        ok, skip, fail, notices = await _scan(files, existing, session)
        _report(ok, skip, fail)

        if update_limits:
            await update_notice_limits(session, False, notices)


def _report(ok: int, skip: int, fail: int) -> None:
    print(f"\n완료: 성공={ok}, 스킵={skip}, 실패={fail}")
    print(f"bid_participants 총 적재: {ok}개 공고")


async def _scan(files, existing: set[str], session) -> tuple[int, int, int, list[tuple[str, dict]]]:
    """파일을 훑어 참여자를 적재하고 (성공, 스킵, 실패, 공고헤더 목록)을 돌려준다.

    session=None 이면 파싱만 한다 (dry-run).
    """
    ok = skip = fail = 0
    notices: list[tuple[str, dict]] = []

    for i, f in enumerate(files, 1):
        data = parse_xls(f)

        if data is None:
            fail += 1
            if fail <= 10 or fail % 50 == 0:
                print(f"[{i}/{len(files)}] FAIL  {f.name}")
            continue

        pid = data["project_id"]
        n   = len(data["participants"])

        # 참여자가 이미 적재됐어도 공고 하한율은 갱신 대상이다.
        notices.append((pid, data["notice"]))

        if pid in existing:
            skip += 1
            continue

        fmt = "7열" if data["participants"][0]["bid_rate"] is None else "12열"

        if session is None:
            print(f"[{i}/{len(files)}] OK {fmt}  {pid}  {n}명")
            ok += 1
            continue

        rows = [
            {
                "project_id":     pid,
                "rank":           p["rank"],
                "bid_amount":     p["bid_amount"],
                "bid_rate":       p["bid_rate"],
                "base_rate":      p["base_rate"],
                "vs_lower_limit": p["vs_lower_limit"],
                "is_winner":      p["is_winner"],
            }
            for p in data["participants"]
        ]
        try:
            await session.execute(INSERT_SQL, rows)
            await session.commit()
        except Exception as e:
            await session.rollback()
            print(f"[{i}/{len(files)}] DB ERR  {pid}: {e}")
            fail += 1
            continue

        existing.add(pid)
        ok += 1
        if ok <= 20 or ok % 50 == 0:
            print(f"[{i}/{len(files)}] OK {fmt}  {pid}  {n}명")

    return ok, skip, fail, notices


def main():
    parser = argparse.ArgumentParser(description="Info21c 참여자 XLS → DB 적재")
    parser.add_argument("--dir",     default=str(DEFAULT_DIR), help="XLS 디렉토리")
    parser.add_argument("--dry-run", action="store_true",      help="파싱만, DB 저장 안 함")
    parser.add_argument("--update-limits", action="store_true",
                        help="공고 헤더의 낙찰하한율/낙찰하한가로 bids_history 하한율 계열 컬럼 갱신")
    args = parser.parse_args()

    asyncio.run(run(Path(args.dir), args.dry_run, args.update_limits))


if __name__ == "__main__":
    main()
