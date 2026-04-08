"""
Info21c 월별 자동 다운로드 매크로.

사전 준비:
  1. Brave를 디버그 포트로 실행:
     "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222
  2. Info21c 로그인 → 공종/지역 필터 직접 설정 (날짜는 스크립트가 자동 변경)
  3. 스크립트 실행:
     python scripts/info21c_pager.py --type 건축 --start 202301 --end 202603
     python scripts/info21c_pager.py --type 조경 --start 202301 --end 202603

결과 파일:
  data/downloads/info21c_건축_20230101_20230131_1.xls
  data/downloads/info21c_건축_20230101_20230131_2.xls
  data/downloads/info21c_건축_20230201_20230228.xls   ← 1페이지면 번호 없음
  ...
"""

import argparse
import asyncio
import time
from calendar import monthrange
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

CDP_URL      = "http://localhost:9222"
DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "downloads"


# ── 날짜 유틸 ─────────────────────────────────────────────────────────────────
def iter_months(start_ym: str, end_ym: str):
    """YYYYMM 범위를 월별로 순회."""
    y, m   = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]),   int(end_ym[4:])
    while (y, m) <= (ey, em):
        last = monthrange(y, m)[1]
        yield f"{y:04d}{m:02d}01", f"{y:04d}{m:02d}{last:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


def get_row_count(path: Path) -> int:
    """XLS 파일 행 수 반환 (헤더 제외)."""
    try:
        import pandas as pd
        df = pd.read_excel(path, engine="xlrd",
                           engine_kwargs={"ignore_workbook_corruption": True})
        return len(df)
    except Exception:
        return 0


def check_month_status(type_name: str, start: str, end: str) -> tuple[str, int]:
    """
    해당 월의 다운로드 상태 반환.
    ('complete', 0)  → 완료 (마지막 파일 < 100행)
    ('missing',  0)  → 없음
    ('partial',  N)  → N페이지까지 있고, N+1부터 필요
    """
    stem = f"info21c_{type_name}_{start}_{end}"

    # 번호 없는 단일 파일
    singles = list(DOWNLOAD_DIR.glob(f"{stem}.xls")) + list(DOWNLOAD_DIR.glob(f"{stem}.xlsx"))
    if singles:
        rows = get_row_count(singles[0])
        return ("complete", 0) if rows < 100 else ("partial", 1)

    # 번호 있는 파일들
    import re
    numbered = []
    for f in list(DOWNLOAD_DIR.glob(f"{stem}_*.xls")) + list(DOWNLOAD_DIR.glob(f"{stem}_*.xlsx")):
        m = re.search(r"_(\d+)\.(xls|xlsx)$", f.name)
        if m:
            numbered.append((int(m.group(1)), f))

    if not numbered:
        return ("missing", 0)

    last_page, last_file = max(numbered, key=lambda x: x[0])
    rows = get_row_count(last_file)
    return ("complete", 0) if rows < 100 else ("partial", last_page)


# ── 날짜 필터 설정 ─────────────────────────────────────────────────────────────
async def set_date_and_search(page, start: str, end: str) -> int:
    """날짜 변경 후 조회. 결과 행 수 반환."""
    fmt_s = f"{start[:4]}-{start[4:6]}-{start[6:]}"
    fmt_e = f"{end[:4]}-{end[4:6]}-{end[6:]}"

    await page.evaluate(
        "(args) => {"
        "  document.querySelector('#config_from_date').value = args[0];"
        "  document.querySelector('#config_to_date').value   = args[1];"
        "}",
        [fmt_s, fmt_e]
    )
    await page.wait_for_timeout(300)
    await page.click("#topSearchBtn")

    try:
        await page.wait_for_selector("table tbody tr[data-key]", timeout=30_000)
    except PWTimeout:
        return 0

    # 페이지 크기 100으로 변경
    changed = await page.evaluate("""
        () => {
            var sel = document.querySelector('select[name=pageSize]');
            if (sel && sel.value !== '100') {
                sel.value = '100';
                sel.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            }
            return false;
        }
    """)

    if changed:
        # AJAX 재로딩 대기: 기존 행 사라졌다 다시 나타날 때까지
        try:
            await page.wait_for_selector("table tbody tr[data-key]", state="detached", timeout=5_000)
        except PWTimeout:
            pass  # 이미 사라진 상태거나 즉시 로드된 경우
        try:
            await page.wait_for_selector("table tbody tr[data-key]", timeout=15_000)
        except PWTimeout:
            pass

    return await page.locator("table tbody tr[data-key]").count()


# ── 다운로드 ──────────────────────────────────────────────────────────────────
async def wait_for_download(download_dir: Path, since: float, timeout: int = 60) -> Path | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        for f in list(download_dir.glob("*.xls")) + list(download_dir.glob("*.xlsx")):
            if not f.name.endswith(".crdownload") and f.stat().st_mtime >= since:
                return f
    return None


async def download_page(page, save_path: Path) -> bool:
    try:
        await page.wait_for_selector("span[name='excelSaveBtn']", timeout=10_000)
    except PWTimeout:
        print("  ⚠ 다운로드 버튼 없음")
        return False

    click_time = time.time() - 1

    await page.click("span[name='excelSaveBtn']")
    await page.wait_for_timeout(1500)

    # 모달 처리
    if await page.locator(".modal.in, .modal[style*='display: block']").count() > 0:
        for sel in ["button:has-text('확인')", ".modal button[type='submit']", ".modal .btn-primary"]:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                break

    new_file = await wait_for_download(DOWNLOAD_DIR, click_time)
    if not new_file:
        print("  ⚠ 파일 감지 실패")
        return False

    new_file.replace(save_path.with_suffix(new_file.suffix))
    print(f"  → {save_path.with_suffix(new_file.suffix).name}")
    return True


# ── 페이지 이동 ───────────────────────────────────────────────────────────────
async def go_next_page(page) -> bool:
    for sel in ["a.next:not(.disabled)", ".paging a.next",
                "li.next:not(.disabled) a", "a[title='다음']", "button[title='다음']"]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.click()
            await page.wait_for_selector("table tbody tr[data-key]", timeout=15_000)
            await page.wait_for_timeout(500)
            return True

    current = await page.evaluate("""
        () => {
            var el = document.querySelector('.paging .active, .paging .on, .pagination .active');
            return el ? parseInt(el.innerText.trim()) : null;
        }
    """)
    if current:
        moved = await page.evaluate(
            f"() => {{ if (typeof goPage==='function') {{ goPage({current+1}); return true; }} return false; }}"
        )
        if moved:
            await page.wait_for_selector("table tbody tr[data-key]", timeout=15_000)
            await page.wait_for_timeout(500)
            return True

    return False


# ── 월 단위 다운로드 ──────────────────────────────────────────────────────────
async def go_to_page(page, target: int) -> bool:
    """특정 페이지 번호로 이동."""
    if target <= 1:
        return True
    moved = await page.evaluate(
        f"() => {{ if (typeof goPage==='function') {{ goPage({target}); return true; }} return false; }}"
    )
    if moved:
        await page.wait_for_selector("table tbody tr[data-key]", timeout=15_000)
        await page.wait_for_timeout(800)
        return True
    # goPage 없으면 버튼 반복 클릭
    for _ in range(target - 1):
        if not await go_next_page(page):
            return False
    return True


async def download_month(page, type_name: str, start: str, end: str, resume_from: int = 1) -> None:
    print(f"\n{'='*50}")
    label = f"{start[:4]}.{start[4:6]}"
    if resume_from > 1:
        print(f"[{label}] 이어받기: {resume_from}페이지부터")
    else:
        print(f"[{label}] 날짜 설정 중...")

    rows = await set_date_and_search(page, start, end)
    if rows == 0:
        print("  → 결과 없음, 건너뜀")
        return

    # 이어받기: 목표 페이지로 이동
    if resume_from > 1:
        print(f"  → {resume_from}페이지로 이동 중...")
        if not await go_to_page(page, resume_from):
            print("  ⚠ 페이지 이동 실패")
            return

    stem = f"info21c_{type_name}_{start}_{end}"
    page_num = resume_from

    while True:
        rows = await page.locator("table tbody tr[data-key]").count()
        print(f"  [페이지 {page_num}] {rows}건")

        if rows == 0:
            break

        # 파일명: 1페이지 단독이면 번호 없이
        save_path = DOWNLOAD_DIR / (stem if rows < 100 and page_num == 1 else f"{stem}_{page_num}")

        ok = await download_page(page, save_path)
        if not ok:
            break

        if rows < 100:
            break

        if not await go_next_page(page):
            break

        page_num += 1

    print(f"  → 완료 ({page_num}페이지)")


# ── 메인 ──────────────────────────────────────────────────────────────────────
async def run(type_name: str, start_ym: str, end_ym: str, skip_existing: bool) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            print("브라우저 연결 실패. Brave를 디버그 포트로 실행했는지 확인하세요:")
            print('  & "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222')
            return

        # Info21c 탭 찾기
        page = None
        for ctx in browser.contexts:
            for p in ctx.pages:
                if "info21c" in p.url:
                    page = p
                    context = ctx
                    break

        if page is None:
            context = browser.contexts[0]
            page = context.pages[0]
            print(f"  ⚠ Info21c 탭 미감지. 현재 탭 사용: {page.url}")

        print(f"  연결된 탭: {page.url}")

        # 다운로드 경로 고정
        cdp = await context.new_cdp_session(page)
        await cdp.send("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(DOWNLOAD_DIR.absolute()),
        })

        months = list(iter_months(start_ym, end_ym))
        print(f"\n총 {len(months)}개월 다운로드 예정 ({start_ym} ~ {end_ym})")

        for i, (start, end) in enumerate(months, 1):
            status, last_page = check_month_status(type_name, start, end)
            print(f"\n진행: {i}/{len(months)}", end="")

            if status == "complete":
                print(f"  [{start[:4]}.{start[4:6]}] 완료됨, 건너뜀")
                continue
            elif status == "partial":
                resume = last_page + 1
                print(f"  [{start[:4]}.{start[4:6]}] {last_page}페이지까지 있음 → {resume}페이지부터")
                await download_month(page, type_name, start, end, resume_from=resume)
            else:
                print()
                await download_month(page, type_name, start, end, resume_from=1)


def main():
    parser = argparse.ArgumentParser(description="Info21c 월별 자동 다운로드")
    parser.add_argument("--type",  required=True, choices=["건축", "조경"], help="공종")
    parser.add_argument("--start", required=True, help="시작 월 YYYYMM (예: 202301)")
    parser.add_argument("--end",   required=True, help="종료 월 YYYYMM (예: 202603)")
    parser.add_argument("--no-skip", action="store_true", help="이미 있는 파일도 재다운로드")
    args = parser.parse_args()

    asyncio.run(run(args.type, args.start, args.end, not args.no_skip))


if __name__ == "__main__":
    main()
