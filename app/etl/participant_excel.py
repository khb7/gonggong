"""
info21c 참여자 Excel 파서.

한 파일에 헤더 블록 / 복수예가 / 참여업체 행 세 덩어리가 순서대로 온다.
셀 위치가 고정이 아니라(라벨 옆 셀에 값, 빈 열 섞임) 라벨을 찾아 그 오른쪽
첫 비어 있지 않은 셀을 값으로 읽는다.

기존 적재(`scripts/info21c_participants.load_participants_to_db`)는 순위·금액·
투찰율만 썼다. 추정가격, A값, 복수예가 15개, 업체 등록번호·업체명·대표자는
파일에 이미 있었는데 버려지고 있었다. 로컬에 16,255개 파일이 있으므로 이 파서로
재다운로드 없이 백필한다.
"""

from __future__ import annotations

from app.etl.project_id import canonical_project_id

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

# ①②…⑮ → 1..15
_CIRCLED = {chr(0x2460 + i): i + 1 for i in range(15)}


@dataclass
class PreliminaryPrice:
    num: int
    price: int
    base_pct: Decimal        # 기초금액 대비 편차 % (97.608 → -2.392)
    is_selected: bool


@dataclass
class ParticipantRow:
    rank: int
    company_id: str | None
    company_name: str | None
    ceo_name: str | None
    bid_amount: int
    bid_rate: Decimal        # 원본 투찰율 컬럼 (소수, 0.886747). 적재 시 재계산 우선


@dataclass
class ParticipantWorkbook:
    project_id: str
    notice_title: str | None
    client_name: str | None
    region: str | None
    license_text: str | None
    open_at: datetime | None
    base_price: int | None
    estimated_price: int | None
    expected_price: int | None
    lower_limit_price: int | None
    declared_limit_rate: Decimal | None
    a_value: int
    preliminary_prices: list[PreliminaryPrice] = field(default_factory=list)
    rows: list[ParticipantRow] = field(default_factory=list)


# ── 셀 값 파싱 ───────────────────────────────────────────────────────────────

def _cells(row) -> list[str]:
    return [str(v).strip() for v in row if pd.notna(v) and str(v).strip() != ""]


def _amount(raw: str | None) -> int | None:
    """'170,984,000' / '155440000' / '169,711,075 (A값:6,784,255)' → 정수. 없으면 None."""
    if raw is None:
        return None
    m = re.match(r"\s*([\d,]+)", raw)
    if not m:
        return None
    digits = m.group(1).replace(",", "")
    return int(digits) if digits else None


def _a_value_in(raw: str | None) -> int:
    if not raw:
        return 0
    m = re.search(r"A\s*값\s*[:：]\s*([\d,]+)", raw)
    return int(m.group(1).replace(",", "")) if m else 0


def _rate(raw: str | None) -> Decimal | None:
    """'87.745%' → Decimal('0.87745'). 빈칸이면 None."""
    if not raw:
        return None
    m = re.match(r"\s*([\d.]+)\s*%?", raw)
    if not m or not m.group(1):
        return None
    return (Decimal(m.group(1)) / 100).normalize()


def _id_str(raw) -> str | None:
    """등록번호. pandas 가 float 로 읽으면 '1358801638.0' 이 되므로 정수부만 남긴다."""
    if raw is None or pd.isna(raw):
        return None
    s = str(raw).strip()
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s or None


def _text(raw) -> str | None:
    if raw is None or pd.isna(raw):
        return None
    s = str(raw).strip()
    return s or None


# ── 헤더 블록 ────────────────────────────────────────────────────────────────

def _header_pairs(df: pd.DataFrame, upto: int) -> dict[str, str]:
    """상단 라벨 행들을 {라벨: 값} 으로 편다. 한 행에 라벨-값 쌍이 둘씩 온다."""
    pairs: dict[str, str] = {}
    for i in range(upto):
        vals = _cells(df.iloc[i])
        j = 0
        while j < len(vals) - 1:
            pairs.setdefault(vals[j], vals[j + 1])
            j += 2
        # 라벨만 있고 값이 빈 경우(낙찰하한율 공란 등)는 setdefault 에 안 걸린다 → None 처리
    return pairs


def _find_row(df: pd.DataFrame, pred) -> int | None:
    for i in range(len(df)):
        if pred(_cells(df.iloc[i])):
            return i
    return None


# ── 복수예가 ─────────────────────────────────────────────────────────────────

def _preliminary(df: pd.DataFrame, start: int, end: int) -> list[PreliminaryPrice]:
    """'복 수 예 가 [ 선택번호: ① ④ ]' 행부터 '최소값' 행 전까지."""
    head = " ".join(_cells(df.iloc[start]))
    selected = {_CIRCLED[c] for c in head if c in _CIRCLED}

    out: list[PreliminaryPrice] = []
    for i in range(start + 1, end):
        row = list(df.iloc[i])
        k = 0
        while k < len(row):
            v = row[k]
            s = str(v).strip() if pd.notna(v) else ""
            if s and s[0] in _CIRCLED:
                num = _CIRCLED[s[0]]
                price = _amount(s[1:])
                # 편차 % 는 같은 행의 오른쪽 첫 숫자 셀
                pct = None
                for m in range(k + 1, len(row)):
                    w = row[m]
                    if pd.notna(w) and str(w).strip() and str(w).strip()[0] not in _CIRCLED:
                        try:
                            pct = Decimal(str(w).strip())
                        except Exception:
                            pct = None
                        k = m
                        break
                if price is not None and pct is not None:
                    out.append(PreliminaryPrice(
                        num=num,
                        price=price,
                        base_pct=(pct - Decimal(100)).normalize(),
                        is_selected=num in selected,
                    ))
            k += 1
    out.sort(key=lambda p: p.num)
    return out


# ── 참여업체 행 ──────────────────────────────────────────────────────────────

def _rows(df: pd.DataFrame, header_row: int) -> list[ParticipantRow]:
    hdr = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[header_row]]

    def col(pattern: str) -> int | None:
        for idx, h in enumerate(hdr):
            if re.search(pattern, h):
                return idx
        return None

    c_rank, c_id, c_name = col(r"순위"), col(r"등록번호"), col(r"업체명")
    c_ceo, c_amt, c_rate = col(r"대표자"), col(r"투찰금액"), col(r"투찰율")
    if c_rank is None or c_amt is None or c_rate is None:
        return []

    out: list[ParticipantRow] = []
    for i in range(header_row + 1, len(df)):
        row = list(df.iloc[i])
        try:
            rank = int(float(str(row[c_rank]).replace(",", "").strip()))
            amount = int(float(str(row[c_amt]).replace(",", "").strip()))
            rate_raw = Decimal(str(row[c_rate]).replace(",", "").strip())
        except (ValueError, TypeError, IndexError, ArithmeticError):
            continue
        # 원본은 % 단위(88.6747). float 를 거치면 0.8867470000000001 이 되므로 Decimal 로 나눈다
        rate = (rate_raw / 100 if rate_raw > 1 else rate_raw).normalize()
        out.append(ParticipantRow(
            rank=rank,
            company_id=_id_str(row[c_id]) if c_id is not None else None,
            company_name=_text(row[c_name]) if c_name is not None else None,
            ceo_name=_text(row[c_ceo]) if c_ceo is not None else None,
            bid_amount=amount,
            bid_rate=rate,
        ))
    return out


# ── 진입점 ───────────────────────────────────────────────────────────────────

def parse_participant_workbook(path: str | Path) -> ParticipantWorkbook:
    path = Path(path)
    suffix = path.suffix.lower()
    kwargs: dict = {"header": None, "engine": "xlrd" if suffix == ".xls" else "openpyxl"}
    if suffix == ".xls":
        kwargs["engine_kwargs"] = {"ignore_workbook_corruption": True}
    df = pd.read_excel(path, **kwargs)

    prelim_start = _find_row(df, lambda c: bool(c) and c[0].replace(" ", "").startswith("복수예가"))
    prelim_end = _find_row(df, lambda c: bool(c) and c[0] == "최소값")
    list_hdr = _find_row(df, lambda c: any(v == "순위" for v in c))

    header_upto = prelim_start if prelim_start is not None else (list_hdr or len(df))
    h = _header_pairs(df, header_upto)

    open_at = None
    if h.get("개찰일시"):
        try:
            open_at = datetime.strptime(h["개찰일시"], "%Y-%m-%d %H:%M")
        except ValueError:
            open_at = None

    return ParticipantWorkbook(
        # 국방부형 번호는 개찰 연도를 붙여야 유일하다 (T-037)
        project_id=canonical_project_id(h.get("공고번호", ""), open_at),
        notice_title=h.get("공고명"),
        client_name=h.get("발주기관"),
        region=h.get("지역"),
        license_text=h.get("공고업종"),
        open_at=open_at,
        base_price=_amount(h.get("기초금액")),
        estimated_price=_amount(h.get("추정가격")),
        expected_price=_amount(h.get("예정가격")),
        lower_limit_price=_amount(h.get("낙찰하한가")),
        declared_limit_rate=_rate(h.get("낙찰하한율")),
        a_value=_a_value_in(h.get("예정가격")),
        preliminary_prices=(
            _preliminary(df, prelim_start, prelim_end)
            if prelim_start is not None and prelim_end is not None else []
        ),
        rows=_rows(df, list_hdr) if list_hdr is not None else [],
    )
