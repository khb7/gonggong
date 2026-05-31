"""
Info21c 상세 페이지에서 복수예가(15개) 데이터 수집.

data/participants/ 에 Excel이 있는 공고 = 이미 방문한 공고.
이 공고들의 상세 페이지를 재방문해서 복수예가 JSON을 추출한다.

사용법:
  python scripts/collect_preliminary_prices.py
  python scripts/collect_preliminary_prices.py --start 20250101 --end 20250531 --type 0002
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import BidPreliminaryPrice, BidsHistory

LOGIN_URL    = "https://www.info21c.net/info21c/member/login/index"
LIST_URL     = "https://infose.info21c.net/info21c/bids/list?bidtype=con&bid_suc=suc"
DEFAULT_ID   = os.getenv("INFO21C_ID", "nw8856")
DEFAULT_PW   = os.getenv("INFO21C_PW", "nw8856")

LICENSE_CODE_MAP = {"0002": "C002", "0023": "C084"}
LICENSE_TYPES    = {"0002": "실내건축", "0023": "조경"}


# ── 로그인 ────────────────────────────────────────────────────────────────────

async def login(page, user_id: str, password: str) -> None:
    print(f"[로그인]")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    try:
        await page.wait_for_selector("input[name='id']", timeout=10_000)
    except PWTimeout:
        pass
    for sel in ["input[name='id']", "#id"]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.fill(user_id)
            break
    for sel in ["input[name='pass']", "#pass"]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.fill(password)
            break
    await page.click("#login_btn")
    await page.wait_for_load_state("networkidle")
    if "login" in page.url.lower():
        raise RuntimeError("로그인 실패")
    print(f"  -> 성공")


# ── 복수예가 추출 ─────────────────────────────────────────────────────────────

async def extract_preliminary_prices(page, url: str) -> tuple[str | None, list[dict]]:
    """
    상세 페이지에서 G2B 공고번호 + 복수예가 15개 추출.
    Returns: (g2b_notice_id, items)
    items: [{"num": int, "price": int, "base_pct": float, "is_selected": bool}]
    """
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        await page.wait_for_timeout(500)
    except Exception as e:
        return None, []

    # 기초금액 0 → 스킵
    basic_val = await page.input_value("#basic")
    if not basic_val or float(basic_val or 0) == 0:
        return None, []

    # G2B 공고번호
    g2b_id = await page.evaluate("""
        () => {
            var rows = document.querySelectorAll('.basic table tbody tr');
            for (var r of rows) {
                var ths = r.querySelectorAll('th');
                var tds = r.querySelectorAll('td');
                for (var i = 0; i < ths.length; i++) {
                    if (ths[i].textContent.includes('공고번호') && tds[i]) {
                        return tds[i].textContent.trim();
                    }
                }
            }
            return null;
        }
    """)

    # 복수예가 JSON
    chart_json = await page.evaluate("""
        () => {
            var el = document.getElementById('multispare-chart');
            return el ? el.getAttribute('data-chart') : null;
        }
    """)

    if not chart_json:
        return g2b_id, []

    try:
        data = json.loads(chart_json)
        items_raw = data.get("items", [])
        if not items_raw:
            return g2b_id, []

        items = []
        for item in items_raw:
            price = item.get("price")
            if not price or price == 0:
                continue
            items.append({
                "num":         int(item["idx"]),
                "price":       int(item["price"]),
                "base_pct":    float(item.get("pct", 0)),
                "is_selected": bool(item.get("selected", False)),
            })
        return g2b_id, items

    except Exception as e:
        print(f"    [!] JSON 파싱 실패: {e}")
        return g2b_id, []


# ── DB 저장 ───────────────────────────────────────────────────────────────────

async def save_preliminary_prices(project_id: str, items: list[dict]) -> int:
    inserted = 0
    async with AsyncSessionLocal() as session:
        for item in items:
            existing = await session.scalar(
                select(BidPreliminaryPrice).where(
                    BidPreliminaryPrice.project_id == project_id,
                    BidPreliminaryPrice.num == item["num"],
                )
            )
            if existing:
                continue
            from decimal import Decimal
            session.add(BidPreliminaryPrice(
                project_id  = project_id,
                num         = item["num"],
                price       = item["price"],
                base_pct    = Decimal(str(item["base_pct"])),
                is_selected = item["is_selected"],
            ))
            inserted += 1

        if inserted > 0:
            await session.commit()
    return inserted


# ── 목록 수집 ─────────────────────────────────────────────────────────────────

async def collect_links(page, start_date: str, end_date: str, license_type: str) -> list[tuple[str, str]]:
    print(f"\n[검색] {start_date}~{end_date} / {LICENSE_TYPES.get(license_type)}")
    await page.goto(LIST_URL, wait_until="networkidle")

    fmt_s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    fmt_e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
    await page.evaluate(
        "(args) => {"
        "  document.querySelector('[name=config_from_date]').value = args[0];"
        "  document.querySelector('[name=config_to_date]').value   = args[1];"
        "}",
        [fmt_s, fmt_e]
    )
    await page.wait_for_timeout(300)

    code_val = LICENSE_CODE_MAP.get(license_type, "C002")
    await page.evaluate(
        "(val) => {"
        "  document.querySelectorAll('input[name=itemcode]').forEach(cb => { cb.checked = false; });"
        "  var t = document.querySelector('input[name=itemcode][value=\"' + val + '\"]');"
        "  if (t) { t.checked = true; t.dispatchEvent(new Event('change', {bubbles:true})); }"
        "}",
        code_val
    )
    await page.wait_for_timeout(300)
    await page.click("#config_search_btn")

    try:
        await page.wait_for_selector("a.list_link", timeout=30_000)
    except PWTimeout:
        return []

    changed = await page.evaluate("""
        () => {
            var sel = document.querySelector('select[name=pageSize]');
            if (!sel) return false;
            sel.value = '100';
            sel.dispatchEvent(new Event('change', {bubbles:true}));
            return true;
        }
    """)
    if changed:
        await page.wait_for_timeout(1500)

    import re
    all_links = []
    page_num = 1
    while True:
        hrefs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a.list_link'))
                       .map(a => a.getAttribute('href') || '')
        """)
        for href in hrefs:
            m = re.search(r"/suc/view/con/([^?&\"']+)", href)
            if m:
                bidid = m.group(1)
                full = f"https://cloud.info21c.net{href}" if href.startswith("/") else href
                all_links.append((bidid, full))

        print(f"  [목록 {page_num}p] {len(hrefs)}건")
        if len(hrefs) < 100:
            break

        moved = False
        for sel in ["a.next:not(.disabled)", ".paging a.next"]:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                await page.wait_for_timeout(1000)
                moved = True
                break
        if not moved:
            break
        page_num += 1

    print(f"  -> 총 {len(all_links)}건")
    return all_links


# ── 기존 수집된 공고 ID 로드 (로그에서) ──────────────────────────────────────

def load_done_bidids() -> set[str]:
    """이미 복수예가가 수집된 project_id 세트."""
    # DB에서 직접 확인은 async라 여기선 빈 세트 반환 (run()에서 처리)
    return set()


# ── 메인 ──────────────────────────────────────────────────────────────────────

async def run(start_date: str, end_date: str, license_type: str,
              user_id: str, password: str, headless: bool) -> None:

    # 이미 복수예가가 있는 project_id 로드
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(BidPreliminaryPrice.project_id).distinct()
        )
        done_projects = {r[0] for r in result.fetchall()}
    print(f"이미 수집된 공고: {len(done_projects)}건")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context()
        page    = await context.new_page()

        await login(page, user_id, password)
        links = await collect_links(page, start_date, end_date, license_type)

        total_ok = total_skip = total_err = 0

        for idx, (bidid, url) in enumerate(links, 1):
            print(f"\n[{idx}/{len(links)}] {bidid}", end="  ")

            try:
                g2b_id, items = await extract_preliminary_prices(page, url)

                if not g2b_id:
                    print("-> 스킵(기초금액 없음)")
                    total_skip += 1
                    continue

                if g2b_id in done_projects:
                    print(f"-> 스킵(이미수집 {g2b_id})")
                    total_skip += 1
                    continue

                if not items:
                    print(f"-> 복수예가 없음 ({g2b_id})")
                    total_skip += 1
                    continue

                n = await save_preliminary_prices(g2b_id, items)
                done_projects.add(g2b_id)
                print(f"-> OK {g2b_id} ({n}건)")
                total_ok += 1

            except Exception as e:
                print(f"-> 오류: {str(e)[:60]}")
                total_err += 1

            await page.wait_for_timeout(200)

        await browser.close()

    print(f"\n=== 완료: {total_ok}건 수집 / {total_skip}건 스킵 / {total_err}건 오류 ===")

    async with AsyncSessionLocal() as session:
        from sqlalchemy import func
        cnt = await session.scalar(
            select(func.count()).select_from(BidPreliminaryPrice)
        )
        proj_cnt = await session.scalar(
            select(func.count(BidPreliminaryPrice.project_id.distinct()))
        )
        print(f"bid_preliminary_prices 총: {cnt}건 / {proj_cnt}개 공고")


def main():
    parser = argparse.ArgumentParser(description="복수예가 데이터 수집")
    parser.add_argument("--start",    required=True, help="시작일 YYYYMMDD")
    parser.add_argument("--end",      required=True, help="종료일 YYYYMMDD")
    parser.add_argument("--type",     choices=["0002", "0023"], required=True)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--id",       default=DEFAULT_ID)
    parser.add_argument("--pw",       default=DEFAULT_PW)
    args = parser.parse_args()

    asyncio.run(run(
        start_date   = args.start,
        end_date     = args.end,
        license_type = args.type,
        user_id      = args.id,
        password     = args.pw,
        headless     = args.headless,
    ))


if __name__ == "__main__":
    main()
