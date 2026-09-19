"""
info21c 개찰 전 공고 수집 (T-035).

목록: https://web.info21c.net/bid/con  (개찰일 기준 오늘 ~ +N일, 공종별)
상세: https://web.info21c.net/bid/view/con/{bidid}

상세 페이지 하나에 분포 엔진 입력이 전부 있다 — 기초금액·추정가격·낙찰하한율·
A값·발주기관·지역·업종·예가변동폭. `/bid/distribution` 은 공고번호로 이 표를
먼저 보고, 없을 때만 G2B 를 부른다.

하한율·A값은 발표가 늦어 공고 초기엔 비어 있을 수 있다. 그래서 개찰 전까지 매번
다시 긁고(`upsert_open_notice` 가 None 으로 기존 값을 지우지 않는다), 기본값은
절대 채우지 않는다.

실행:
    python scripts/info21c_open_notices.py --days 21
    python scripts/info21c_open_notices.py --days 21 --headless
"""

import argparse
import asyncio
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.crud_collect import upsert_open_notice
from app.db.session import AsyncSessionLocal, engine
from app.etl.info21c_notice import parse_open_notice_text
from scripts.info21c_participants import (
    DEFAULT_ID, DEFAULT_PW, LICENSE_CODE_MAP, LICENSE_TYPES, TIMEOUT, login,
)

LIST_URL = "https://web.info21c.net/bid/con"
DETAIL_RE = re.compile(r"/bid/view/con/([^?&\"'/]+)")


async def collect_links(page, start: date, end: date, code_val: str) -> list[tuple[str, str]]:
    """목록 검색 → 전체 페이지의 (bidid, url). 참여자 leg 의 목록 로직과 같은 폼이다."""
    await page.goto(LIST_URL, wait_until="networkidle")
    await page.evaluate(
        "(a) => {"
        "  var col = document.querySelector('select[name=config_date_column]');"
        "  if (col) { col.value = 'constdt'; col.dispatchEvent(new Event('change', {bubbles:true})); }"
        "  document.querySelector('[name=config_from_date]').value = a[0];"
        "  document.querySelector('[name=config_to_date]').value   = a[1];"
        "  document.querySelectorAll('input[name=itemcode]').forEach(cb => { cb.checked = false; });"
        "  var t = document.querySelector('input[name=itemcode][value=\"' + a[2] + '\"]');"
        "  if (t) { t.checked = true; t.dispatchEvent(new Event('change', {bubbles:true})); }"
        "}",
        [start.isoformat(), end.isoformat(), code_val],
    )
    await page.wait_for_timeout(300)
    # /bid/con 에는 'G2B 자기정보 자동등록' 안내 레이어(#siljeok_notice)가 떠서 검색
    # 버튼 클릭을 가로챈다. 레이어를 걷어내고 JS 로 클릭한다 (포인터 가로채기 무관).
    await page.evaluate(
        "() => { document.querySelectorAll('#siljeok_notice, .modal-backdrop').forEach(e => e.remove());"
        " var b = document.querySelector('#config_search_btn'); if (b) b.click(); }"
    )
    try:
        await page.wait_for_selector("a.list_link", timeout=TIMEOUT)
    except PWTimeout:
        return []

    changed = await page.evaluate(
        "() => { var s = document.querySelector('select[name=pageSize]'); if (!s) return false;"
        " s.value = '100'; s.dispatchEvent(new Event('change', {bubbles:true})); return true; }"
    )
    if changed:
        await page.wait_for_timeout(1500)

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    page_num = 1
    while True:
        hrefs = await page.evaluate(
            "() => Array.from(document.querySelectorAll('a.list_link')).map(a => a.getAttribute('href') || '')"
        )
        for href in hrefs:
            m = DETAIL_RE.search(href)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append((m.group(1), href if href.startswith("http") else f"https://web.info21c.net{href}"))
        print(f"  [목록 {page_num}p] {len(hrefs)}건", flush=True)
        if len(hrefs) < 100:
            break
        moved = await page.evaluate("""
            () => {
                var items = Array.from(document.querySelectorAll('ul.pagination li.page-item'));
                var cur = items.find(li => li.classList.contains('disabled') && /^\\d+$/.test(li.innerText.trim()));
                if (cur) {
                    var n = parseInt(cur.innerText.trim());
                    var next = items.find(li => !li.classList.contains('disabled') && parseInt(li.innerText.trim()) === n + 1);
                    if (next) { next.querySelector('a').click(); return true; }
                }
                var last = items[items.length - 1];
                if (last && !last.classList.contains('disabled')) { last.querySelector('a').click(); return true; }
                return false;
            }
        """)
        if not moved:
            break
        await page.wait_for_selector("a.list_link", timeout=15_000)
        await page.wait_for_timeout(500)
        page_num += 1
    return out


async def fetch_detail_text(page, url: str) -> str:
    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    await page.wait_for_timeout(300)
    return await page.evaluate("() => document.body.innerText")


async def run(*, days: int, headless: bool, user_id: str, password: str) -> dict:
    start = date.today()
    end = start + timedelta(days=days)
    stats = {"listed": 0, "inserted": 0, "updated": 0, "no_limit": 0, "errors": 0}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(accept_downloads=False)
        page = await ctx.new_page()
        await login(page, user_id, password)

        links: list[tuple[str, str]] = []
        for code, name in LICENSE_TYPES.items():
            print(f"\n[개찰 전 공고] {start}~{end} / {name}({code})")
            got = await collect_links(page, start, end, LICENSE_CODE_MAP.get(code, "C002"))
            known = {b for b, _ in links}
            links += [(b, u) for b, u in got if b not in known]
        stats["listed"] = len(links)
        print(f"\n상세 {len(links)}건")

        async with AsyncSessionLocal() as session:
            for i, (bidid, url) in enumerate(links, 1):
                try:
                    text = await fetch_detail_text(page, url)
                    n = parse_open_notice_text(text)
                    inserted = await upsert_open_notice(session, n, info21c_bidid=bidid)
                    stats["inserted" if inserted else "updated"] += 1
                    if n.legal_limit_rate is None:
                        stats["no_limit"] += 1
                    if i % 50 == 0:
                        print(f"  {i}/{len(links)}", flush=True)
                except Exception as e:
                    stats["errors"] += 1
                    print(f"  [!] {bidid}: {type(e).__name__}: {e}", flush=True)

        await ctx.close()
        await browser.close()

    await engine.dispose()
    print(
        f"\n=== 개찰 전 공고: 목록 {stats['listed']} / 신규 {stats['inserted']} / 갱신 {stats['updated']} "
        f"/ 하한율 미발표 {stats['no_limit']} / 오류 {stats['errors']} ==="
    )
    return stats


def main():
    ap = argparse.ArgumentParser(description="info21c 개찰 전 공고 수집")
    ap.add_argument("--days", type=int, default=21, help="오늘부터 며칠 뒤 개찰까지 (기본 21)")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--id", default=DEFAULT_ID)
    ap.add_argument("--pw", default=DEFAULT_PW)
    a = ap.parse_args()
    asyncio.run(run(days=a.days, headless=a.headless, user_id=a.id, password=a.pw))


if __name__ == "__main__":
    main()
