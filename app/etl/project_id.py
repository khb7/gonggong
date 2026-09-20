"""
공고 식별자 정규화 (T-037).

국방부 계열 공고번호는 `LPK0148-1` 처럼 **해마다 재사용**된다. 나라장터 번호가 아니라
부대별 일련번호라 2025 년 예초용역과 2026 년 창호 교체공사가 같은 번호를 받는다.
그걸 그대로 project_id 로 쓰면 목록 leg 는 뒤에 온 공고를 "이미 있음" 으로 건너뛰고,
참여자 leg 는 두 공고의 참여자를 한 공고 밑에 합친다 (자사 투찰 85건 중 18건 확인,
영향권 1,649 공고 / 131만 행).

그래서 국방부형 번호에는 개찰 연도를 붙인다:

    LPK0148-1  +  개찰 2026-09-08  →  LPK0148-1@2026

G2B 번호(`R26BK01705597-000`, `20241234791-00`)는 전역 유일이라 손대지 않는다.
연도를 모르면 원본을 돌려준다 — 그때는 충돌 가능성이 남지만 없는 값을 지어내지 않는다.
"""

from __future__ import annotations

import re
from datetime import date, datetime

# 국방부형: 영문 3 + 숫자 4 + '-' + 숫자 1  (예: LPK0148-1, UMM0535-1, HDG0053-1)
_MILITARY_RE = re.compile(r"^[A-Z]{3}\d{4}-\d$")
_CANONICAL_RE = re.compile(r"^([A-Z]{3}\d{4}-\d)@(\d{4})$")


def is_military_notice_no(raw: str | None) -> bool:
    return bool(raw) and _MILITARY_RE.fullmatch(raw.strip()) is not None


def canonical_project_id(raw: str | None, open_date: date | datetime | None) -> str:
    """저장용 project_id. 국방부형이면 개찰 연도를 붙이고, 아니면 원본 그대로."""
    s = (raw or "").strip()
    if not s:
        return s
    if _CANONICAL_RE.fullmatch(s):
        return s
    if _MILITARY_RE.fullmatch(s) and open_date is not None:
        return f"{s}@{open_date.year}"
    return s


def split_project_id(pid: str) -> tuple[str, int | None]:
    """`LPK0148-1@2026` → (`LPK0148-1`, 2026). 다른 형식은 (원본, None)."""
    m = _CANONICAL_RE.fullmatch((pid or "").strip())
    if m:
        return m.group(1), int(m.group(2))
    return (pid or "").strip(), None


def lookup_pattern(raw: str | None) -> str | None:
    """사용자가 연도 없이 `LPK0148-1` 만 넣었을 때 LIKE 로 찾을 패턴. 국방부형이 아니면 None."""
    s = (raw or "").strip()
    if not _MILITARY_RE.fullmatch(s):
        return None
    return f"{s}@%"
