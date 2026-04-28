"""
Info21c participants_*.xls → bids_history DB 적재 스크립트.

파일 형식: 공고명 레이아웃 (공고별 1파일)
  행 0: 공고명
  행 1: 업종(col2) / 지역(col8)
  행 2: 공고번호(col2) / 발주기관(col8)
  행 3: 개찰일시(col2) / 낙찰금액(col8)
  행 4: 기초금액(col2) / 낙찰하한율(col8)
  행 5: 예산금액(col2) / 예가/기초(col8) ← 사정률
  행 6: 낙찰자선정가(col2) / 투찰/기초(col8)
  행15: 참여업체수 헤더 텍스트

사용법:
  python scripts/etl_participants.py
  python scripts/etl_participants.py --dir "G:/내 드라이브/gonggong/participants"
  python scripts/etl_participants.py --resume   # 이미 처리된 파일 스킵
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import xlrd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db.session import AsyncSessionLocal
from app.db.models import BidsHistory, BidLicenseType
from app.db.normalize import parse_license_types
from sqlalchemy import select

DEFAULT_DIR = Path("G:/내 드라이브/gonggong/participants")
LOG_FILE    = Path("data/downloads/_participants_etl.log")


# ── 정규화 유틸 ────────────────────────────────────────────────────────────────

# normalize.py의 parse_license_types 사용 (위에서 import됨)


def parse_percent(raw) -> float | None:
    """'85.995%' 또는 '100.4829% (0.4829%)' → float (소수, 예: 0.85995)"""
    if raw is None:
        return None
    s = str(raw).strip()
    m = re.search(r"([\d.]+)%", s)
    if not m:
        return None
    val = float(m.group(1))
    return val / 100.0


def parse_price(raw) -> int | None:
    """'8,135,922,331 원' 또는 float → int"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        v = int(raw)
        return v if v > 0 else None
    s = re.sub(r"[^\d]", "", str(raw))
    return int(s) if s else None


def parse_participants(raw) -> int:
    """'전체 참여업체수 [ 참여업체수: 2038] ...' → 2038"""
    if raw is None:
        return 0
    m = re.search(r"참여업체수[:\s]*(\d+)", str(raw))
    return int(m.group(1)) if m else 0


def parse_date(raw) -> "datetime.date | None":
    if raw is None:
        return None
    s = str(raw).strip()
    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"]:
        try:
            return datetime.strptime(s[:len(fmt)], fmt).date()
        except ValueError:
            continue
    return None


# ── 파일 파싱 ─────────────────────────────────────────────────────────────────

def parse_participants_xls(path: Path) -> dict | None:
    """participants_*.xls 1개 → bids_history 레코드 dict (실패 시 None)"""
    try:
        wb = xlrd.open_workbook(str(path), ignore_workbook_corruption=True)
        ws = wb.sheet_by_index(0)
    except Exception as e:
        raise ValueError(f"xlrd 오픈 실패: {e}")

    if ws.nrows < 7:
        raise ValueError(f"행 수 부족: {ws.nrows}")

    def cell(r, c):
        try:
            v = ws.cell_value(r, c)
            return v if v != "" else None
        except IndexError:
            return None

    # 포맷 확인 (행0 col0 = '공고명')
    if str(cell(0, 0) or "").strip() != "공고명":
        raise ValueError("공고명 레이아웃 아님")

    project_id   = str(cell(2, 2) or "").strip()
    client_name  = str(cell(2, 8) or "").strip() or None
    region_raw   = str(cell(1, 8) or "").strip()
    license_types = parse_license_types(str(cell(1, 2) or ""))
    bid_date     = parse_date(cell(3, 2))
    base_price   = parse_price(cell(4, 2))
    lower_limit  = parse_percent(cell(4, 8))
    adj_rate     = parse_percent(cell(5, 8))   # 예가/기초
    winner_price = parse_price(str(cell(6, 2) or ""))
    participants = parse_participants(cell(15, 0)) if ws.nrows > 15 else 0

    # 유효성 검사
    if not project_id:
        raise ValueError("공고번호 없음")
    if not license_types:
        raise ValueError(f"공종 매핑 불가: {cell(1, 2)!r}")
    if not base_price or base_price <= 0:
        raise ValueError(f"기초금액 이상: {cell(4, 2)!r}")
    if adj_rate is None or not (0.95 < adj_rate < 1.05):
        raise ValueError(f"사정률 범위 밖: {cell(5, 8)!r} → {adj_rate}")
    if lower_limit is None:
        raise ValueError(f"낙찰하한율 파싱 실패: {cell(4, 8)!r}")

    # 지역 정규화 (공백 정리)
    region = region_raw if region_raw else "기타"

    return {
        "project_id":    project_id,
        "client_name":   client_name,
        "client_id":     None,
        "region":        region,
        "_license_types": license_types,
        "base_price":    base_price,
        "lower_limit_rate": lower_limit,
        "adjustment_rate":  adj_rate,
        "winner_price":  winner_price,
        "participants":  participants,
        "bid_date":      bid_date,
        "bid_type":      "적격심사",
        "price_method":  "복수예비가격",
        "g2b_code":      None,
    }


# ── DB 적재 ───────────────────────────────────────────────────────────────────

async def load_one(record: dict) -> str:
    """'inserted' | 'skipped'"""
    from decimal import Decimal
    async with AsyncSessionLocal() as session:
        exists = await session.scalar(
            select(BidsHistory.id).where(BidsHistory.project_id == record["project_id"])
        )
        if exists:
            return "skipped"
        session.add(BidsHistory(
            project_id       = record["project_id"],
            client_name      = record["client_name"],
            client_id        = record["client_id"],
            region           = record["region"],
            base_price       = record["base_price"],
            lower_limit_rate = Decimal(str(record["lower_limit_rate"])),
            adjustment_rate  = Decimal(str(record["adjustment_rate"])),
            winner_price     = record["winner_price"],
            participants     = record["participants"],
            bid_date         = record["bid_date"],
            bid_type         = record["bid_type"],
            price_method     = record["price_method"],
            g2b_code         = record["g2b_code"],
        ))
        for lt in record.get("_license_types", []):
            session.add(BidLicenseType(
                project_id = record["project_id"],
                type_name  = lt["type_name"],
                size       = lt["size"],
                is_mutual  = lt["is_mutual"],
                is_primary = lt["is_primary"],
            ))
        await session.commit()
        return "inserted"


# ── 로그 ─────────────────────────────────────────────────────────────────────

def load_done() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    done = set()
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OK:"):
            done.add(line[3:].strip())
    return done


def log_ok(filename: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"OK:{filename}  [{ts}]\n")


# ── 메인 ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="participants XLS → bids_history")
    parser.add_argument("--dir",     default=str(DEFAULT_DIR))
    parser.add_argument("--resume",  action="store_true", help="처리된 파일 스킵")
    args = parser.parse_args()

    files = sorted(Path(args.dir).glob("participants_*.xls"))
    if not files:
        print(f"파일 없음: {args.dir}/participants_*.xls")
        sys.exit(1)

    done = load_done() if args.resume else set()
    to_process = [f for f in files if f.name not in done]

    print(f"총 {len(files)}개 / 처리 대상 {len(to_process)}개"
          + (f" ({len(files) - len(to_process)}개 스킵)" if args.resume else ""))
    print("=" * 60)

    inserted = skipped = errors = 0

    for i, f in enumerate(to_process, 1):
        try:
            record = parse_participants_xls(f)
            result = await load_one(record)
            if result == "inserted":
                inserted += 1
                log_ok(f.name)
            else:
                skipped += 1
                log_ok(f.name)

            if i % 50 == 0 or i == len(to_process):
                print(f"  [{i}/{len(to_process)}] 신규:{inserted} 중복:{skipped} 오류:{errors}")

        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"  ERR {f.name}: {e}")

    print("=" * 60)
    print(f"완료: 신규 {inserted}건 / 중복 {skipped}건 / 오류 {errors}건")


if __name__ == "__main__":
    asyncio.run(main())
