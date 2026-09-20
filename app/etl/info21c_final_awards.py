"""
info21c 최종낙찰현황(/suc/last/con) 표 행 파서.

표 한 행: 번호 | 공고명/공고번호 | 발주기관 | 개찰일 | 낙찰금액 | 업체명 | 대표자 | 주소

낙찰정보(/suc/con)의 1순위는 "개찰 1순위" 지 계약 업체가 아니다. 적격심사
탈락·포기로 2·3순위가 계약하는 경우가 있는데 이 표가 그 결과다.
`bid_participants.is_winner = (rank == 1)` 가정이 얼마나 맞는지 여기서 잰다.
"""

from __future__ import annotations

from app.etl.project_id import canonical_project_id

import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class FinalAward:
    project_id: str
    notice_title: str | None
    client_name: str | None
    open_date: date | None
    award_amount: int | None
    company_name: str | None
    ceo_name: str | None
    address: str | None
    info21c_bidid: str | None


_NOTICE_NO = re.compile(r"\[([A-Za-z0-9\-]{6,})\]\s*$")


def _amount(raw: str) -> int | None:
    d = raw.replace(",", "").strip()
    return int(d) if d.isdigit() else None


def _date(raw: str) -> date | None:
    raw = raw.strip()
    for fmt in ("%y.%m.%d", "%Y-%m-%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_final_award_row(cells: list[str], link: str | None) -> FinalAward | None:
    if len(cells) < 8:
        return None
    title_cell = cells[1].strip()
    m = _NOTICE_NO.search(title_cell)
    if not m:
        return None
    bidid = None
    if link:
        lm = re.search(r"/suc/view/con/([^?&\"'/]+)", link)
        bidid = lm.group(1) if lm else None
    return FinalAward(
        project_id=canonical_project_id(m.group(1), _date(cells[3])),
        notice_title=title_cell[: m.start()].strip() or None,
        client_name=cells[2].strip() or None,
        open_date=_date(cells[3]),
        award_amount=_amount(cells[4]),
        company_name=cells[5].strip() or None,
        ceo_name=cells[6].strip() or None,
        address=cells[7].strip() or None,
        info21c_bidid=bidid,
    )
