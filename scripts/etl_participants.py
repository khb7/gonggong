"""
data/participants/ 의 Excel 파일들을 bid_participants DB에 일괄 적재.

Excel 파일에서 G2B 공고번호를 직접 추출하므로 상세 페이지 재방문 불필요.

사용법:
  python scripts/etl_participants.py
  python scripts/etl_participants.py --dir data/participants
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
from decimal import Decimal
from sqlalchemy import select, func

from app.db.session import AsyncSessionLocal
from app.db.models import BidParticipants, BidsHistory

PARTICIPANTS_DIR = Path(__file__).parent.parent / "data" / "participants"


def extract_g2b_id(excel_path: Path) -> str | None:
    """Excel 파일에서 G2B 공고번호 추출."""
    try:
        suffix = excel_path.suffix.lower()
        if suffix == ".xls":
            df = pd.read_excel(excel_path, header=None, engine="xlrd",
                               engine_kwargs={"ignore_workbook_corruption": True})
        else:
            df = pd.read_excel(excel_path, header=None, engine="openpyxl")

        for i in range(min(10, len(df))):
            row = df.iloc[i].tolist()
            for j, val in enumerate(row):
                # 공고번호 레이블 옆 값 탐색
                if isinstance(val, str) and "공고번호" in val:
                    if j + 2 < len(row) and pd.notna(row[j + 2]):
                        return str(row[j + 2]).strip()
                # R/L로 시작하는 공고번호 패턴 직접 탐색
                if isinstance(val, str) and len(val) > 8 and "-" in val and val[0] in "RLG":
                    return val.strip()
    except Exception as e:
        print(f"  [!] G2B ID 추출 실패 ({excel_path.name}): {e}")
    return None


def extract_participants(excel_path: Path) -> list[dict]:
    """Excel 파일에서 참여자 데이터 추출."""
    try:
        suffix = excel_path.suffix.lower()
        read_kwargs: dict = {"header": None}
        if suffix == ".xls":
            read_kwargs["engine"] = "xlrd"
            read_kwargs["engine_kwargs"] = {"ignore_workbook_corruption": True}
        else:
            read_kwargs["engine"] = "openpyxl"

        df_raw = pd.read_excel(excel_path, **read_kwargs)

        header_row = None
        for i, row in df_raw.iterrows():
            if any("순위" in str(v) for v in row if pd.notna(v)):
                header_row = i
                break

        if header_row is None:
            return []

        read_kwargs["header"] = header_row
        df = pd.read_excel(excel_path, **read_kwargs)
        df.columns = df.columns.str.strip()

        col_rank   = next((c for c in df.columns if "순위" in str(c)), None)
        col_amount = next((c for c in df.columns if "투찰금액" in str(c)), None)
        col_rate   = next((c for c in df.columns if "투찰율" in str(c)), None)

        if not all([col_rank, col_amount, col_rate]):
            return []

        records = []
        for _, row in df.iterrows():
            try:
                rank = int(float(str(row[col_rank]).replace(",", "").strip()))
                amount = int(float(str(row[col_amount]).replace(",", "").strip()))
                rate_raw = float(str(row[col_rate]).replace(",", "").strip())
                bid_rate = Decimal(str(rate_raw / 100 if rate_raw > 1 else rate_raw))
                records.append({
                    "rank": rank,
                    "bid_amount": amount,
                    "bid_rate": bid_rate,
                    "is_winner": (rank == 1),
                })
            except (ValueError, TypeError):
                continue

        return records

    except Exception as e:
        print(f"  [!] 참여자 추출 실패: {e}")
        return []


async def process_file(excel_path: Path, project_ids_in_db: set[str]) -> tuple[int, str]:
    g2b_id = extract_g2b_id(excel_path)
    if not g2b_id:
        return 0, "G2B ID 추출 실패"

    if g2b_id not in project_ids_in_db:
        return 0, f"bids_history 미존재 ({g2b_id})"

    records = extract_participants(excel_path)
    if not records:
        return 0, "참여자 데이터 없음"

    inserted = 0
    async with AsyncSessionLocal() as session:
        for r in records:
            existing = await session.scalar(
                select(BidParticipants).where(
                    BidParticipants.project_id == g2b_id,
                    BidParticipants.rank == r["rank"],
                )
            )
            if existing:
                continue
            # NOTE: 이 스크립트는 bid_participants 만 적재한다. bids_history 의
            # bid_type/price_method 는 여기서 설정하지 않으며, bids_history ETL
            # (info21c 적재 스크립트) 에서 bid_type='적격심사',
            # price_method='복수예비가격' 으로 설정해야 한다.
            session.add(BidParticipants(
                project_id = g2b_id,
                rank       = r["rank"],
                bid_amount = r["bid_amount"],
                bid_rate   = r["bid_rate"],
                is_winner  = r["is_winner"],
            ))
            inserted += 1

        if inserted > 0:
            await session.commit()

    return inserted, f"{g2b_id} → {inserted}건"


async def main(participants_dir: Path) -> None:
    files = sorted(participants_dir.glob("*.xls*"))
    print(f"처리할 파일: {len(files)}개")

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BidsHistory.project_id))
        project_ids_in_db = {r[0] for r in result.fetchall()}
    print(f"bids_history project_id: {len(project_ids_in_db)}건")

    total_inserted = 0
    total_skipped = 0

    for i, f in enumerate(files, 1):
        inserted, msg = await process_file(f, project_ids_in_db)
        if inserted > 0:
            print(f"  [{i}/{len(files)}] OK: {msg}")
            total_inserted += inserted
        else:
            print(f"  [{i}/{len(files)}] SKIP: {f.name} ({msg})")
            total_skipped += 1

    print(f"\n=== 완료: 적재 {total_inserted}건 / 스킵 {total_skipped}건 ===")

    async with AsyncSessionLocal() as session:
        cnt = await session.scalar(select(func.count()).select_from(BidParticipants))
        proj_cnt = await session.scalar(
            select(func.count(BidParticipants.project_id.distinct()))
        )
        print(f"bid_participants 총: {cnt}건 / {proj_cnt}개 공고")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=str(PARTICIPANTS_DIR))
    args = parser.parse_args()
    asyncio.run(main(Path(args.dir)))
