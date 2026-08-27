"""
Info21c 클린 CSV → bids_history DB 적재 스크립트.

사전 조건:
  - info21c_downloader.py 로 다운로드된 CSV 파일 사용
  - 내보내기 옵션: CSV, 쉼표 구분자, 리포트제목 OFF, 필터세부사항 OFF

사용법:
  python scripts/etl_csv.py --file data/downloads/info21c_조경_20250101_20250131.xls
  python scripts/etl_csv.py --file data/downloads/info21c_건축_20250101_20250131.xls

기대 컬럼 (첫 행이 헤더):
  입찰공고번호, 개찰순위, 면허업종제한목록, 낙찰하한율, 투찰율,
  낙찰자선정여부, 투찰일자, 낙찰방법, 수요기관, 수요기관지역,
  수요기관사업자등록번호, 기초금액, 예산가격, 투찰금액, 입찰참여자수

있으면 좋은 컬럼 (없어도 동작):
  예정가격결정방식, 1순위사정율, g2b분류
"""

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import BidsHistory, BidLicenseType, BidTag
from app.db.normalize import parse_license_types

# 공고명 대괄호 태그. 예) '... 유지보수공사 [정][실적][공의][A값][순]' → 정/실적/공의/A값/순
_TAG_RE = re.compile(r"\[([^\]]{1,20})\]")


def parse_notice_tags(title: str) -> list[str]:
    """공고명에서 대괄호 태그를 뽑는다. 중복 제거, 원래 순서 유지."""
    if not title or pd.isna(title):
        return []
    seen: list[str] = []
    for t in _TAG_RE.findall(str(title)):
        t = t.strip()
        if t and t not in seen:
            seen.append(t)
    return seen


def normalize_region(raw: str) -> str:
    """지역 컬럼 값 그대로 사용. '전국,경기', '경기', '전국' 등."""
    if not raw or pd.isna(raw):
        return "기타"
    return str(raw).strip()


# normalize.py의 parse_license_types 사용 (위에서 import됨)


# ── 낙찰방법 정규화 ───────────────────────────────────────────────────────────
def normalize_bid_type(raw: str) -> str:
    """'적격심사제' / '적격심사' → '적격심사', 나머지 → '기타'"""
    if not raw or pd.isna(raw):
        return "기타"
    raw = str(raw).strip()
    if "적격" in raw:
        return "적격심사"
    if "종합심사" in raw:
        return "종합심사"
    if "최저가" in raw:
        return "최저가"
    if "협상" in raw:
        return "협상"
    return "기타"


# ── 예정가격결정방식 정규화 ────────────────────────────────────────────────────
def normalize_price_method(raw: str) -> str:
    """'복수예비가격' / '고정예정가격' 외 → '기타'"""
    if not raw or pd.isna(raw):
        return "기타"
    raw = str(raw).strip()
    if "복수예비가격" in raw:
        return "복수예비가격"
    if "고정예정가격" in raw:
        return "고정예정가격"
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
            "공고번호":           "입찰공고번호",
            "발주기관":           "수요기관",
            "예정가격":           "예산가격",
            "1순위투찰금액":      "투찰금액",
            "개찰일":             "투찰일자",
            "업종":               "면허업종제한목록",
            "지역":               "수요기관지역",
            "업체수":             "입찰참여자수",
            "1순위사정율(100%)":  "1순위사정율",    # 신포맷 컬럼명
            "G2B물품분류":        "g2b분류",        # 신포맷 컬럼명
        })
        # 요약 포맷에서 없는 컬럼 기본값으로 채우기
        df["개찰순위"]              = "1"
        df["낙찰하한율"]            = 0.87745   # fallback; 낙찰하한가 컬럼 있으면 루프에서 재계산
        if "입찰참여자수" not in df.columns:
            df["입찰참여자수"]      = 0
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

            # 사정률: 낙찰금액 / 기초금액
            # 요약 포맷에 1순위기초대비(%) 컬럼이 있으면 우선 사용
            raw_kd = row.get("1순위기초대비", None)
            if raw_kd is not None and str(raw_kd).strip() not in ("", "nan"):
                adjustment_rate = float(str(raw_kd).replace(",", "").strip()) / 100.0
            else:
                adjustment_rate = winner_price / base_price
            if not (0.70 < adjustment_rate < 1.00):
                err_value += 1
                continue

            # 공종 파싱 → 빈 리스트면 제외
            license_types = parse_license_types(row.get("면허업종제한목록", ""))
            if not license_types:
                err_type += 1
                continue

            # 낙찰하한율: 낙찰하한가 컬럼 있으면 낙찰하한가/예정가격으로 계산
            raw_llh = row.get("낙찰하한가", None)
            if raw_llh is not None and str(raw_llh).strip() not in ("", "nan", "0"):
                lower_limit = float(str(raw_llh).replace(",", "").strip()) / est_price
            elif lower_limit > 1:
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

            # ── price_method ─────────────────────────────────────────────
            raw_pm = row.get("예정가격결정방식", "")
            price_method = normalize_price_method(str(raw_pm) if raw_pm else "")

            # ── 공고명 / 태그 ─────────────────────────────────────────────
            # 태그는 참여자 수를 크게 가른다: [시담] 평균 1.0개사(경쟁입찰 아님),
            # [현필] 3.1개사, [관내] 67.8개사, [순] 895.6개사.
            raw_title = row.get("공고명", None)
            notice_title = str(raw_title).strip() if raw_title and str(raw_title).strip() != "nan" else None
            if notice_title and len(notice_title) > 300:
                notice_title = notice_title[:300]
            tags = parse_notice_tags(notice_title or "")
            has_a_value = "A값" in tags

            # ── 사정률 (예정가격/기초금액) ─────────────────────────────────
            # adjustment_rate(=낙찰가/기초금액)와 다른 값이다. 원본 컬럼 우선,
            # 없으면 예정가격/기초금액으로 계산 (둘 다 원본에 있다).
            preprice_rate = None
            raw_pp = row.get("예가/기초(100%)", None)
            if raw_pp is not None and str(raw_pp).strip() not in ("", "nan"):
                try:
                    preprice_rate = float(str(raw_pp).replace(",", "").strip()) / 100.0
                except ValueError:
                    preprice_rate = None
            if preprice_rate is None:
                preprice_rate = est_price / base_price
            # 복수예비가격 생성범위는 최대 ±6% 대다. 벗어나면 값이 깨진 행.
            if not (0.90 < preprice_rate < 1.10):
                preprice_rate = None

            # ── 낙찰하한가 원값 ───────────────────────────────────────────
            lower_limit_price = None
            if raw_llh is not None and str(raw_llh).strip() not in ("", "nan", "0"):
                try:
                    lower_limit_price = int(float(str(raw_llh).replace(",", "").strip()))
                except ValueError:
                    lower_limit_price = None

            # ── g2b_code ─────────────────────────────────────────────────
            raw_g2b = row.get("g2b분류", None)
            g2b_code = str(raw_g2b).strip() if raw_g2b and str(raw_g2b).strip() not in ("", "nan") else None
            if g2b_code and len(g2b_code) > 50:
                g2b_code = g2b_code[:50]

            records.append({
                "project_id":       str(row["입찰공고번호"]).strip(),
                "client_name":      str(row.get("수요기관", "")).strip() or None,
                "client_id":        str(row.get("수요기관사업자등록번호", "")).strip() or None,
                "region":           normalize_region(row.get("수요기관지역", "")),
                "_license_types":   license_types,
                "_tags":            tags,
                "notice_title":     notice_title,
                "preprice_rate":    preprice_rate,
                "est_price":        est_price,
                "lower_limit_price": lower_limit_price,
                "has_a_value":      has_a_value,
                "bid_type":         normalize_bid_type(row.get("낙찰방법", "")),
                "price_method":     price_method,
                "base_price":       base_price,
                "lower_limit_rate": lower_limit,
                "adjustment_rate":  adjustment_rate,
                "winner_price":     winner_price,
                "participants":     participants,
                "bid_date":         bid_date,
                "g2b_code":         g2b_code,
            })
        except (ValueError, TypeError):
            err_parse += 1

    print(f"  → 드롭: 값 오류 {err_value}건, 공종 미매핑 {err_type}건, 파싱 오류 {err_parse}건")
    df_final = pd.DataFrame(records)
    print(f"  → DB 적재 대상: {len(df_final)}건")
    return df_final


async def _sync_tags(session, project_id: str, tags: list[str]) -> None:
    """공고의 bid_tags 를 주어진 목록과 정확히 일치시킨다.

    추가만 하면 안 된다 — 같은 공고가 정정공고로 여러 파일에 다른 공고명으로
    들어오면 태그가 누적되어, 최신 공고명에서 계산한 has_a_value 와 어긋난다.
    """
    with session.no_autoflush:
        rows = await session.scalars(
            select(BidTag).where(BidTag.project_id == project_id)
        )
        existing = {r.tag: r for r in rows}

    for tag in tags:
        if tag not in existing:
            session.add(BidTag(project_id=project_id, tag=tag))
    for tag, obj in existing.items():
        if tag not in tags:
            await session.delete(obj)


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
    seen_in_batch: set[str] = set()  # 파일 내 중복 project_id 방지

    async with AsyncSessionLocal() as session:
        for _, row in df.iterrows():
            pid = row["project_id"]
            if pid in seen_in_batch:
                updated += 1  # 파일 내 중복 → 스킵
                continue
            seen_in_batch.add(pid)

            with session.no_autoflush:
                existing = await session.scalar(
                    select(BidsHistory).where(BidsHistory.project_id == pid)
                )
            if existing:
                if upsert:
                    existing.client_name      = row["client_name"]
                    existing.client_id        = row["client_id"]
                    existing.region           = row["region"]
                    existing.bid_type         = row["bid_type"]
                    existing.price_method     = row["price_method"]
                    existing.base_price       = row["base_price"]
                    existing.lower_limit_rate = row["lower_limit_rate"]
                    existing.adjustment_rate  = row["adjustment_rate"]
                    existing.winner_price     = row["winner_price"]
                    existing.participants     = row["participants"]
                    existing.bid_date         = row["bid_date"]
                    existing.g2b_code         = row["g2b_code"]
                    existing.notice_title      = row["notice_title"]
                    existing.preprice_rate     = row["preprice_rate"]
                    existing.est_price         = row["est_price"]
                    existing.lower_limit_price = row["lower_limit_price"]
                    existing.has_a_value       = row["has_a_value"]
                    # 태그는 기존 공고에도 넣어야 한다. bid_license_types 와 달리
                    # 신규 경로만 두면 이미 적재된 공고엔 영원히 안 들어간다.
                    await _sync_tags(session, pid, row.get("_tags", []))
                    updated += 1
                else:
                    updated += 1  # skipped count
                continue

            session.add(BidsHistory(
                project_id       = row["project_id"],
                client_name      = row["client_name"],
                client_id        = row["client_id"],
                region           = row["region"],
                bid_type         = row["bid_type"],
                price_method     = row["price_method"],
                base_price       = row["base_price"],
                lower_limit_rate = row["lower_limit_rate"],
                adjustment_rate  = row["adjustment_rate"],
                winner_price     = row["winner_price"],
                participants     = row["participants"],
                bid_date         = row["bid_date"],
                g2b_code         = row["g2b_code"],
                notice_title      = row["notice_title"],
                preprice_rate     = row["preprice_rate"],
                est_price         = row["est_price"],
                lower_limit_price = row["lower_limit_price"],
                has_a_value       = row["has_a_value"],
            ))

            # bid_tags 삽입 (신규 공고)
            for tag in row.get("_tags", []):
                session.add(BidTag(project_id=row["project_id"], tag=tag))

            # bid_license_types 삽입 (신규 공고만)
            for lt in row.get("_license_types", []):
                session.add(BidLicenseType(
                    project_id = row["project_id"],
                    type_name  = lt["type_name"],
                    size       = lt["size"],
                    is_mutual  = lt["is_mutual"],
                    is_primary = lt["is_primary"],
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
    parser.add_argument("--upsert", action="store_true", help="기존 레코드 업데이트 (기본: 스킵)")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"파일을 찾을 수 없습니다: {file_path}")
        sys.exit(1)

    df = extract_and_transform(file_path)
    inserted, skipped = await load_to_db(df, upsert=args.upsert)
    label = "업데이트" if args.upsert else "스킵"
    print(f"\n완료: 신규 {inserted}건 / {label} {skipped}건")


if __name__ == "__main__":
    asyncio.run(main())
