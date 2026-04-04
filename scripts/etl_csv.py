"""
Info21c 클린 CSV → bids_history DB 적재 스크립트.

사전 조건:
  - info21c_downloader.py 로 다운로드된 CSV 파일 사용
  - 내보내기 옵션: CSV, 쉼표 구분자, 리포트제목 OFF, 필터세부사항 OFF

사용법:
  python scripts/etl_csv.py --file data/downloads/info21c_0002_20250101_20251231.csv
  python scripts/etl_csv.py --file data/downloads/info21c_0023_20250101_20251231.csv

기대 컬럼 (첫 행이 헤더):
  입찰공고번호, 개찰순위, 면허업종제한목록, 낙찰하한율, 투찰율,
  낙찰자선정여부, 투찰일자, 낙찰방법, 수요기관, 수요기관지역,
  수요기관사업자등록번호, 기초금액, 예산가격, 투찰금액, 입찰참여자수
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import BidsHistory


def normalize_region(raw: str) -> str:
    """지역 컬럼 값 그대로 사용. '전국,경기', '경기', '전국' 등."""
    if not raw or pd.isna(raw):
        return "기타"
    return str(raw).strip()


# ── 공종 정규화 ───────────────────────────────────────────────────────────────
def normalize_project_type(raw: str) -> str | None:
    """
    '건축공사업[0002]', '0002', '실내건축[대]', '조경식재공사업[0023]', '조경(조경.체육시설)[대]' 등
    → '실내건축' / '조경'
    복합 공종('|' 구분) 또는 매핑 없는 코드 → None (필터링)
    """
    if not raw or pd.isna(raw):
        return None
    raw = str(raw)
    if "|" in raw:
        return None  # 복수 공종 제외
    if "0002" in raw or "실내건축" in raw:
        return "실내건축"
    if "0023" in raw or "조경" in raw:
        return "조경"
    return None


# ── 낙찰방법 정규화 ───────────────────────────────────────────────────────────
def normalize_bid_type(raw: str) -> str:
    """'적격심사제' / '적격심사' → '적격심사', 나머지 → '기타'"""
    if not raw or pd.isna(raw):
        return "기타"
    raw = str(raw).strip()
    if "적격" in raw:
        return "적격심사"
    if "최저가" in raw:
        return "최저가"
    if "협상" in raw:
        return "협상"
    return "기타"


# ── ETL ───────────────────────────────────────────────────────────────────────
def extract_and_transform(file_path: Path) -> pd.DataFrame:
    print(f"1. 파일 읽는 중: {file_path}")

    suffix = file_path.suffix.lower()
    df = None

    if suffix in (".xls", ".xlsx"):
        # xls: xlrd 필요 / xlsx: openpyxl 필요
        engine = "xlrd" if suffix == ".xls" else "openpyxl"
        try:
            kwargs = {"engine": engine}
            if suffix == ".xls":
                # Info21c XLS 파일은 OLE2 구조 일부 손상 → relaxed 모드 필요
                kwargs["engine_kwargs"] = {"ignore_workbook_corruption": True}
            df = pd.read_excel(file_path, **kwargs)
            df.columns = df.columns.str.strip().str.replace("\ufeff", "")
            print(f"  → Excel({suffix}), 행 수: {len(df)}")
        except Exception as e:
            raise ValueError(f"Excel 파일을 읽을 수 없습니다: {file_path} ({e})")
    else:
        # CSV: 인코딩 자동 감지
        for enc in ["utf-8-sig", "utf-8", "cp949", "utf-16"]:
            try:
                df = pd.read_csv(file_path, encoding=enc)
                df.columns = df.columns.str.strip().str.replace("\ufeff", "")
                print(f"  → 인코딩: {enc}, 행 수: {len(df)}")
                break
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue

    if df is None:
        raise ValueError(f"파일을 읽을 수 없습니다: {file_path}")

    # ── 포맷 감지 및 컬럼 정규화 ───────────────────────────────────────────────
    # 포맷 A (상세): 입찰공고번호, 개찰순위, 면허업종제한목록, 낙찰하한율, 기초금액, ... 포함
    # 포맷 B (요약): 공고번호, 낙찰기관, 낙찰금액, 예산가격, 1순위낙찰금액, 기준/예가(100%), 구분 포함
    if "입찰공고번호" not in df.columns and "공고번호" in df.columns:
        print("  → 요약 포맷(Info21c 낙찰현황) 감지 → 컬럼 매핑 적용")
        df = df.rename(columns={
            "공고번호":       "입찰공고번호",
            "발주기관":       "수요기관",
            "예정가격":       "예산가격",
            "1순위투찰금액":  "투찰금액",
            "개찰일":         "투찰일자",
            "업종":           "면허업종제한목록",
            "지역":           "수요기관지역",      # 지역 컬럼 직접 사용
        })
        # 요약 포맷에서 없는 컬럼 기본값으로 채우기
        df["개찰순위"]              = "1"
        df["낙찰하한율"]            = 0.87745
        df["입찰참여자수"]          = 0
        if "수요기관지역" not in df.columns:
            df["수요기관지역"]      = "기타"      # 구버전 파일 (지역 컬럼 없는 경우)
        df["수요기관사업자등록번호"] = None
        df["낙찰방법"]              = "적격심사"

    # 필수 컬럼 확인
    required = ["입찰공고번호", "개찰순위", "면허업종제한목록", "낙찰하한율",
                "기초금액", "예산가격", "투찰금액", "입찰참여자수"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}\n실제 컬럼: {df.columns.tolist()}")

    # 낙찰자(개찰순위 1) 만 추출
    df["개찰순위"] = df["개찰순위"].astype(str).str.strip()
    df_winner = df[df["개찰순위"] == "1"].copy()
    print(f"  → 1순위(낙찰자) 행: {len(df_winner)}건")

    records = []
    err_parse = 0
    err_value = 0
    err_type  = 0

    for _, row in df_winner.iterrows():
        try:
            base_price  = int(float(str(row["기초금액"]).replace(",", "").strip()))
            est_price   = int(float(str(row["예산가격"]).replace(",", "").strip()))
            winner_price = int(float(str(row["투찰금액"]).replace(",", "").strip()))
            participants = int(float(str(row["입찰참여자수"]).replace(",", "").strip()))
            lower_limit  = float(str(row["낙찰하한율"]).replace(",", "").strip())

            # 유효성 검사 (participants=0은 요약 포맷에서 허용)
            if base_price <= 0 or est_price <= 0:
                err_value += 1
                continue

            # 사정률: 예산가격(예정가격) / 기초금액
            adjustment_rate = est_price / base_price
            if not (0.95 < adjustment_rate < 1.05):
                err_value += 1
                continue

            # 공종 정규화
            project_type = normalize_project_type(row.get("면허업종제한목록", ""))
            if not project_type:
                err_type += 1
                continue

            # 낙찰하한율: 80~90 범위(퍼센트)면 /100
            if lower_limit > 1:
                lower_limit = lower_limit / 100.0

            # 날짜
            bid_date = None
            raw_date = str(row.get("투찰일자", "")).strip()
            if raw_date and raw_date != "nan":
                for fmt in ["%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d", "%y.%m.%d", "%y-%m-%d"]:
                    try:
                        from datetime import datetime
                        bid_date = datetime.strptime(raw_date, fmt).date()
                        break
                    except ValueError:
                        continue

            records.append({
                "project_id":       str(row["입찰공고번호"]).strip(),
                "client_name":      str(row.get("수요기관", "")).strip() or None,
                "client_id":        str(row.get("수요기관사업자등록번호", "")).strip() or None,
                "region":           normalize_region(row.get("수요기관지역", "")),
                "project_type":     project_type,
                "bid_type":         normalize_bid_type(row.get("낙찰방법", "")),
                "base_price":       base_price,
                "lower_limit_rate": lower_limit,
                "adjustment_rate":  adjustment_rate,
                "winner_price":     winner_price,
                "participants":     participants,
                "bid_date":         bid_date,
            })
        except (ValueError, TypeError):
            err_parse += 1

    print(f"  → 드롭: 값 오류 {err_value}건, 공종 미매핑 {err_type}건, 파싱 오류 {err_parse}건")
    df_final = pd.DataFrame(records)
    print(f"  → DB 적재 대상: {len(df_final)}건")
    return df_final


async def load_to_db(df: pd.DataFrame, upsert: bool = False) -> tuple[int, int]:
    """
    upsert=False (기본): 신규만 삽입, 기존 project_id 스킵
    upsert=True: 기존 레코드도 region 포함 전체 필드 업데이트
    """
    if df.empty:
        print("적재할 데이터가 없습니다.")
        return 0, 0

    print(f"2. DB 적재 중... ({len(df)}건, upsert={upsert})")
    inserted = 0
    updated  = 0

    async with AsyncSessionLocal() as session:
        for _, row in df.iterrows():
            existing = await session.scalar(
                select(BidsHistory).where(BidsHistory.project_id == row["project_id"])
            )
            if existing:
                if upsert:
                    existing.client_name      = row["client_name"]
                    existing.client_id        = row["client_id"]
                    existing.region           = row["region"]
                    existing.project_type     = row["project_type"]
                    existing.bid_type         = row["bid_type"]
                    existing.base_price       = row["base_price"]
                    existing.lower_limit_rate = row["lower_limit_rate"]
                    existing.adjustment_rate  = row["adjustment_rate"]
                    existing.winner_price     = row["winner_price"]
                    existing.participants     = row["participants"]
                    existing.bid_date         = row["bid_date"]
                    updated += 1
                else:
                    updated += 1  # skipped count
                continue

            session.add(BidsHistory(
                project_id       = row["project_id"],
                client_name      = row["client_name"],
                client_id        = row["client_id"],
                region           = row["region"],
                project_type     = row["project_type"],
                bid_type         = row["bid_type"],
                base_price       = row["base_price"],
                lower_limit_rate = row["lower_limit_rate"],
                adjustment_rate  = row["adjustment_rate"],
                winner_price     = row["winner_price"],
                participants     = row["participants"],
                bid_date         = row["bid_date"],
            ))
            inserted += 1

            if (inserted + updated) % 500 == 0:
                await session.commit()
                print(f"  → {inserted}건 적재 / {updated}건 {'업데이트' if upsert else '스킵'}...")

        await session.commit()

    label = "업데이트" if upsert else "스킵"
    print(f"  → 신규 {inserted}건 적재 / 기존 {updated}건 {label}")
    return inserted, updated


async def main():
    parser = argparse.ArgumentParser(description="Info21c 클린 CSV → DB 적재")
    parser.add_argument("--file", required=True, help="다운로드된 CSV 파일 경로")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"파일을 찾을 수 없습니다: {file_path}")
        sys.exit(1)

    df = extract_and_transform(file_path)
    inserted, skipped = await load_to_db(df)
    print(f"\n완료: 신규 {inserted}건 / 스킵 {skipped}건")


if __name__ == "__main__":
    asyncio.run(main())
