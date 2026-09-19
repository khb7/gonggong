"""
info21c 개찰 전 공고 상세(/bid/view/con/{id}) 텍스트 파서.

브라우저에서 `document.body.innerText` 로 긁은 텍스트를 받는다. DOM 구조가 아니라
라벨 → 값 순서에 의존하므로 프론트의 붙여넣기 파서(frontend/src/lib/info21c.ts)와
같은 방식이다. 이 페이지 하나에 분포 엔진 입력이 전부 있다:

    기초금액 · 추정가격 · 낙찰하한율 · A값 · 발주기관 · 지역 · 업종 · 예가변동폭

값이 없으면 None 으로 둔다. 하한율·A값은 발표가 늦는 경우가 있어 공고 시점에
비어 있을 수 있는데, 그때 기본값을 채우면 하한가 미달로 탈락한다 (CLAUDE.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class OpenNotice:
    project_id: str
    notice_title: str | None
    client_name: str | None
    demand_org: str | None
    region: str | None
    license_text: str | None
    contract_method: str | None      # 수의 / 적격 / 일반 …
    price_method: str                # 복수예비가격 / 고정예정가격 / 기타
    preprice_range_pct: int | None   # 예가변동폭 ±N (%). 2=국가계약, 3=지방계약
    legal_limit_rate: Decimal | None
    a_value: int
    base_price: int | None
    estimated_price: int | None
    bid_close_at: datetime | None
    open_at: datetime | None


_TAG_WORDS = ("관내", "수의", "기초", "A값", "긴급", "재공고", "정정", "순", "공가", "급", "제한내역")


def _after(label: str, text: str) -> str | None:
    """'라벨\\t값' 또는 '라벨\\n값' 에서 값을 꺼낸다. 라벨 뒤 첫 비어 있지 않은 토큰."""
    m = re.search(re.escape(label) + r"[ \t]*(?:\t|\n)+[ \t]*([^\t\n]+)", text)
    if not m:
        return None
    v = m.group(1).strip()
    return v or None


def _amount_after(label: str, text: str) -> int | None:
    m = re.search(re.escape(label) + r"[\s\t]*\n?[\s\t]*([\d,]+)\s*원", text)
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _rate_after(label: str, text: str) -> Decimal | None:
    m = re.search(re.escape(label) + r"[ \t]*([\d.]+)\s*%", text)
    if not m:
        return None
    return (Decimal(m.group(1)) / 100).normalize()


def _dt_after(label: str, text: str) -> datetime | None:
    m = re.search(
        re.escape(label) + r"[\s\t]*\n?[\s\t]*(\d{4})년 (\d{2})월 (\d{2})일 (\d{2})시 (\d{2})분",
        text,
    )
    if not m:
        return None
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return datetime(y, mo, d, h, mi)


def _title(text: str) -> str | None:
    """'기본정보' 바로 윗줄이 제목이다. 뒤에 붙은 태그 뭉치는 뗀다."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "기본정보" and i > 0:
            raw = lines[i - 1].strip()
            # ']' 뒤에 태그 단어들이 공백 없이 이어 붙는다: '...[(구리시)]관내수의기초A값'
            m = re.match(r"^(.*[\]\)])([가-힣A-Z값]+)$", raw)
            if m and any(w in m.group(2) for w in _TAG_WORDS):
                return m.group(1).strip()
            return raw
    return None


def parse_open_notice_text(text: str) -> OpenNotice:
    text = text.replace("\r\n", "\n")
    pid = _after("공고번호", text)
    if not pid:
        raise ValueError("공고번호를 찾을 수 없다")

    rng = None
    rng_raw = _after("예가변동폭", text)
    if rng_raw:
        m = re.search(r"\+\s*(\d+)", rng_raw) or re.search(r"(\d+)", rng_raw)
        if m:
            rng = int(m.group(1))

    pm_raw = _after("예가방법", text) or ""
    if "복수" in pm_raw:
        price_method = "복수예비가격"
    elif "고정" in pm_raw or "단일" in pm_raw:
        price_method = "고정예정가격"
    else:
        price_method = "기타"

    return OpenNotice(
        project_id=pid,
        notice_title=_title(text),
        client_name=_after("발주기관", text),
        demand_org=_after("수요기관", text),
        region=_after("지역", text),
        license_text=_after("업종", text),
        contract_method=_after("계약방법", text),
        price_method=price_method,
        preprice_range_pct=rng,
        legal_limit_rate=_rate_after("낙찰하한율", text),
        a_value=_amount_after("A값", text) or 0,
        base_price=_amount_after("기초금액", text),
        estimated_price=_amount_after("추정가격", text),
        bid_close_at=_dt_after("투찰마감일시", text),
        open_at=_dt_after("개찰일시", text),
    )
