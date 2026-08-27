"""
Info21c 월별 전체 데이터 수집 스크립트 (페이지 넘기기 포함).

사용법:
  python scripts/info21c_collect_all.py --type 0002 --start 202401 --end 202512
  python scripts/info21c_collect_all.py --type 0023 --start 202401 --end 202512

결과 파일:
  data/downloads/info21c_0002_20240101_20240131.xlsx       ← 1페이지 이하
  data/downloads/info21c_0002_20240101_20240131_p2.xlsx    ← 2페이지
  ...

이미 완료된 월은 자동 스킵.
"""

import argparse
import asyncio
import os
import re
import sys
from calendar import monthrange
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Download, TimeoutError as PWTimeout

LOGIN_URL    = "https://www.info21c.net/info21c/member/login/index"
LIST_URL     = "https://infose.info21c.net/info21c/bids/list?bidtype=con&bid_suc=suc"
DEFAULT_ID   = os.getenv("INFO21C_ID", "nw8856")
DEFAULT_PW   = os.getenv("INFO21C_PW", "nw8856")
DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "downloads"
LICENSE_TYPES     = {"0002": "실내건축", "0023": "조경"}
LICENSE_CODE_MAP  = {"0002": "C002", "0023": "C084"}
TIMEOUT = 30_000


# ── 월 범위 순회 ───────────────────────────────────────────────────────────────
def iter_months(start_ym: str, end_ym: str):
    y, m   = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]),   int(end_ym[4:])
    while (y, m) <= (ey, em):
        last = monthrange(y, m)[1]
        yield f"{y:04d}{m:02d}01", f"{y:04d}{m:02d}{last:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


# ── 완료 여부 확인 ─────────────────────────────────────────────────────────────
def get_row_count(path: Path) -> int:
    try:
        import pandas as pd
        df = pd.read_excel(path, header=None)
        # 헤더 행 제외: 첫 행이 '입찰공고번호' 등이면 데이터는 -1
        return max(0, len(df) - 1)
    except Exception:
        return 0


def check_month_done(license_type: str, start: str, end: str) -> tuple[bool, int]:
    """
    (완료여부, 마지막 페이지번호) 반환.
    완료: 마지막 파일 행수 < 100
    """
    stem = f"info21c_{license_type}_{start}_{end}"

    # 페이지 없는 단일 파일
    for ext in [".xlsx", ".xls"]:
        f = DOWNLOAD_DIR / f"{stem}{ext}"
        if f.exists():
            rows = get_row_count(f)
            return (rows < 100, 1)

    # _p2, _p3 ... 파일
    numbered = []
    for f in list(DOWNLOAD_DIR.glob(f"{stem}_p*.xlsx")) + list(DOWNLOAD_DIR.glob(f"{stem}_p*.xls")):
        m = re.search(r"_p(\d+)\.(xlsx|xls)$", f.name)
        if m:
            numbered.append((int(m.group(1)), f))

    if not numbered:
        return (False, 0)

    last_page, last_file = max(numbered, key=lambda x: x[0])
    rows = get_row_count(last_file)
    return (rows < 100, last_page)


# ── 로그인 ─────────────────────────────────────────────────────────────────────
async def login(page, user_id: str, password: str) -> None:
    print("[로그인] www.info21c.net ...")
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

    if "login" in page.url.lower() or "member" in page.url.lower():
        raise RuntimeError(f"로그인 실패: {page.url}")
    print(f"  → 성공 ({page.url})")


# ── 검색 조건 설정 + 결과 수 반환 ─────────────────────────────────────────────
async def set_filters_and_search(page, start: str, end: str, license_type: str) -> int:
    fmt_s = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    fmt_e = f"{end[:4]}-{end[4:6]}-{end[6:]}"
    code  = LICENSE_CODE_MAP[license_type]

    await page.goto(LIST_URL, wait_until="networkidle")
    await page.evaluate(
        "(args) => {"
        "  document.querySelector('[name=config_from_date]').value = args[0];"
        "  document.querySelector('[name=config_to_date]').value   = args[1];"
        "}",
        [fmt_s, fmt_e]
    )
    await page.evaluate(
        "(val) => {"
        "  document.querySelectorAll('input[name=itemcode]').forEach(cb => cb.checked=false);"
        "  var t = document.querySelector('input[name=itemcode][value=\"'+val+'\"]');"
        "  if (t) { t.checked=true; t.dispatchEvent(new Event('change',{bubbles:true})); }"
        "}",
        code
    )
    await page.wait_for_timeout(300)
    await page.click("#config_search_btn")

    try:
        await page.wait_for_selector("a.list_link", timeout=TIMEOUT)
    except PWTimeout:
        return 0

    changed = await page.evaluate("""
        () => {
            var s = document.querySelector('select[name=pageSize]');
            if (!s) return false;
            s.value='100'; s.dispatchEvent(new Event('change',{bubbles:true})); return true;
        }
    """)
    if changed:
        await page.wait_for_timeout(1500)

    return await page.locator("a.list_link").count()


# ── 페이지 이동 ────────────────────────────────────────────────────────────────
async def go_next_page(page) -> bool:
    # ul.pagination li.page-item 구조 (info21c Bootstrap 방식)
    clicked = await page.evaluate("""
        () => {
            var items = Array.from(document.querySelectorAll('ul.pagination li.page-item'));
            // 현재 페이지: disabled + 숫자
            var cur = items.find(li =>
                li.classList.contains('disabled') && /^\\d+$/.test(li.innerText.trim())
            );
            if (cur) {
                var curNum = parseInt(cur.innerText.trim());
                var next = items.find(li =>
                    !li.classList.contains('disabled') &&
                    parseInt(li.innerText.trim()) === curNum + 1
                );
                if (next) { next.querySelector('a').click(); return true; }
            }
            // 위 방법 실패 시: » 버튼 (마지막 li, disabled 아닌 경우)
            var last = items[items.length - 1];
            if (last && !last.classList.contains('disabled')) {
                last.querySelector('a').click();
                return true;
            }
            return false;
        }
    """)
    if clicked:
        try:
            await page.wait_for_selector("a.list_link", timeout=15_000)
        except PWTimeout:
            pass
        await page.wait_for_timeout(500)
        return True
    return False


async def go_to_page(page, target: int) -> bool:
    if target <= 1:
        return True
    for _ in range(target - 1):
        if not await go_next_page(page):
            return False
    return True


# ── 엑셀 다운로드 ──────────────────────────────────────────────────────────────
async def download_current_page(page, save_stem: Path) -> tuple[bool, int]:
    """현재 페이지 엑셀 다운로드. (성공여부, 행수) 반환."""
    btn_sel = "button[name='list_excel_btn']"
    try:
        await page.wait_for_selector(btn_sel, timeout=TIMEOUT)
    except PWTimeout:
        print("  ⚠ 엑셀 버튼 없음")
        return False, 0

    async with page.expect_download(timeout=60_000) as dl_info:
        await page.click(btn_sel)
        await page.wait_for_timeout(1500)

        modal_visible = await page.locator(
            ".modal.in, .modal[style*='display: block'], .modal[style*='display:block']"
        ).count() > 0
        if modal_visible:
            for sel in ["button:has-text('확인')", "button:has-text('다운로드')",
                        ".modal button[type='submit']", ".modal .btn-primary"]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click()
                    break

    dl: Download = await dl_info.value
    suffix = Path(dl.suggested_filename).suffix or ".xlsx"
    out = save_stem.with_suffix(suffix)
    await dl.save_as(str(out))

    rows = get_row_count(out)
    print(f"  → 저장: {out.name} ({rows}건)")
    return True, rows


# ── 월 수집 ────────────────────────────────────────────────────────────────────
async def collect_month(page, license_type: str, start: str, end: str, resume_page: int) -> None:
    label = f"{start[:4]}.{start[4:6]}"
    stem  = f"info21c_{license_type}_{start}_{end}"

    row_count = await set_filters_and_search(page, start, end, license_type)
    if row_count == 0:
        print(f"  [{label}] 결과 없음")
        return

    print(f"  [{label}] {row_count}건 로드됨 (첫 페이지)")

    if resume_page > 1:
        print(f"  [{label}] {resume_page}페이지부터 이어받기...")
        if not await go_to_page(page, resume_page):
            print(f"  ⚠ 페이지 이동 실패")
            return

    page_num = resume_page
    while True:
        visible = await page.locator("a.list_link").count()
        if visible == 0:
            break

        # 파일명: 1페이지 단독이면 번호 없이
        if page_num == 1:
            save_stem = DOWNLOAD_DIR / stem
        else:
            save_stem = DOWNLOAD_DIR / f"{stem}_p{page_num}"

        ok, rows = await download_current_page(page, save_stem)
        if not ok:
            break

        if rows < 100:
            break

        if not await go_next_page(page):
            print(f"  [{label}] 다음 페이지 없음 (p{page_num} 마지막)")
            break

        page_num += 1
        await page.wait_for_timeout(500)

    print(f"  [{label}] 완료 ({page_num}페이지)")


# ── 메인 ──────────────────────────────────────────────────────────────────────
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


async def run(license_type: str, start_ym: str, end_ym: str, user_id: str, password: str) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    months = list(iter_months(start_ym, end_ym))
    type_name = LICENSE_TYPES[license_type]
    print(f"\n=== {type_name}({license_type}) {start_ym}~{end_ym} 수집 시작 ({len(months)}개월) ===\n")

    async with async_playwright() as pw:
        launch_kwargs = dict(headless=True)
        if Path(BRAVE_PATH).exists():
            launch_kwargs["executable_path"] = BRAVE_PATH
            print(f"  Brave 브라우저 사용")
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        await login(page, user_id, password)

        for i, (start, end) in enumerate(months, 1):
            label = f"{start[:4]}.{start[4:6]}"
            done, last_page = check_month_done(license_type, start, end)

            print(f"\n[{i}/{len(months)}] {label}", end="")
            if done:
                print(f"  → 이미 완료됨, 스킵")
                continue
            elif last_page > 0:
                print(f"  → {last_page}페이지까지 있음, {last_page+1}페이지부터 이어받기")
                await collect_month(page, license_type, start, end, resume_page=last_page + 1)
            else:
                print()
                await collect_month(page, license_type, start, end, resume_page=1)

        await browser.close()

    print(f"\n=== 수집 완료 ===")
    print("다음 단계: python scripts/etl_batch.py --pattern 'info21c_*.xlsx'")


def main():
    parser = argparse.ArgumentParser(description="Info21c 월별 전체 수집 (페이지 넘기기 포함)")
    parser.add_argument("--type",  required=True, choices=["0002", "0023"])
    parser.add_argument("--start", required=True, help="시작 월 YYYYMM")
    parser.add_argument("--end",   required=True, help="종료 월 YYYYMM")
    parser.add_argument("--id",    default=DEFAULT_ID)
    parser.add_argument("--pw",    default=DEFAULT_PW)
    args = parser.parse_args()
    asyncio.run(run(args.type, args.start, args.end, args.id, args.pw))


if __name__ == "__main__":
    main()
