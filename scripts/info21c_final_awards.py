"""
info21c 최종낙찰현황 수집 (T-035).

https://web.info21c.net/suc/last/con — 실제 계약 업체 목록. GET 파라미터로 검색되고
한 페이지 100건이라 상세 페이지를 열 필요가 없다.

낙찰정보(/suc/con)의 1순위는 개찰 1순위일 뿐이다. 적격심사 탈락·포기로 후순위가
계약하는 비율을 `bid_participants` 의 rank=1 과 대조해 잰다
(`scripts/validate_data.py` 의 [최종낙찰] 절).

실행:
    python scripts/info21c_final_awards.py --days 30
    python scripts/info21c_final_awards.py --start 20260101 --end 20260131 --headless
"""

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.crud_collect import upsert_final_award
from app.db.session import AsyncSessionLocal, engine
from app.etl.info21c_final_awards import parse_final_award_row
from scripts.info21c_participants import DEFAULT_ID, DEFAULT_PW, login

BASE = "https://web.info21c.net/suc/last/con"

# 최종낙찰현황의 업종 select 는 목록 페이지 체크박스와 코드가 다르다.
# C081=실내건축[대], C084=조경(식재.시설물)[대], C002=건축 (참여자 leg 가 C002 로 받는다)
SEARCH_CODES = {"C081": "실내건축", "C084": "조경", "C002": "건축"}

_ROWS_JS = """
() => {
  const tbs = [...document.querySelectorAll('table')]
    .filter(t => [...t.querySelectorAll('th')].some(th => /낙찰금액/.test(th.innerText)));
  const tb = tbs[tbs.length - 1];
  if (!tb) return [];
  return [...tb.querySelectorAll('tbody tr')].map(tr => ({
    cells: [...tr.querySelectorAll('td')].map(td => td.innerText.trim()),
    link: (tr.querySelector('a[href*="/suc/view/con/"]') || {}).getAttribute
          ? tr.querySelector('a[href*="/suc/view/con/"]').getAttribute('href') : null,
  }));
}
"""


async def run(*, start: date, end: date, headless: bool, user_id: str, password: str) -> dict:
    stats = {"rows": 0, "inserted": 0, "updated": 0, "skipped": 0}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await login(page, user_id, password)

        async with AsyncSessionLocal() as session:
            for code, name in SEARCH_CODES.items():
                print(f"\n[최종낙찰] {start}~{end} / {name}({code})")
                pg = 1
                while True:
                    url = (
                        f"{BASE}?page={pg}&pageSize=100&search_code={code}"
                        f"&from_date={start.isoformat()}&to_date={end.isoformat()}"
                    )
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await page.wait_for_timeout(400)
                    rows = await page.evaluate(_ROWS_JS)
                    print(f"  [{pg}p] {len(rows)}건", flush=True)
                    for r in rows:
                        stats["rows"] += 1
                        rec = parse_final_award_row(r["cells"], r.get("link"))
                        if rec is None:
                            stats["skipped"] += 1
                            continue
                        ins = await upsert_final_award(session, rec)
                        stats["inserted" if ins else "updated"] += 1
                    if len(rows) < 100:
                        break
                    pg += 1

        await ctx.close()
        await browser.close()
    await engine.dispose()
    print(
        f"\n=== 최종낙찰: 행 {stats['rows']} / 신규 {stats['inserted']} / 갱신 {stats['updated']} "
        f"/ 건너뜀 {stats['skipped']} ==="
    )
    return stats


def main():
    ap = argparse.ArgumentParser(description="info21c 최종낙찰현황 수집")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--id", default=DEFAULT_ID)
    ap.add_argument("--pw", default=DEFAULT_PW)
    a = ap.parse_args()
    if a.start and a.end:
        s = datetime.strptime(a.start, "%Y%m%d").date()
        e = datetime.strptime(a.end, "%Y%m%d").date()
    else:
        e = date.today() - timedelta(days=1)
        s = e - timedelta(days=a.days - 1)
    asyncio.run(run(start=s, end=e, headless=a.headless, user_id=a.id, password=a.pw))


if __name__ == "__main__":
    main()
