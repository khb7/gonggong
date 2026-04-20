"""
Info21c 낙찰결과 참여자 데이터 수집 스크립트.

사전 준비:
  1. Brave를 디버그 포트로 실행:
     "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222
  2. Info21c 로그인 → 공종/지역 필터 직접 설정 (날짜는 스크립트가 자동 변경)
  3. 스크립트 실행:
     python scripts/info21c_participants.py --type 건축 --start 202301 --end 202603
     python scripts/info21c_participants.py --type 조경 --start 202301 --end 202603

결과 파일:
  G:\\내 드라이브\\gonggong\\participants\\participants_{bidid}_{page}.xls
로그 파일:
  data/downloads/_participants.log
"""

import argparse
import asyncio
import re
import time
from calendar import monthrange
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

CDP_URL      = "http://localhost:9222"
DOWNLOAD_DIR = Path("G:/내 드라이브/gonggong/participants")
LOG_FILE     = Path("data/downloads/_participants.log")


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def iter_months(start_ym: str, end_ym: str):
    y, m   = int(start_ym[:4]), int(start_ym[4:])
    ey, em = int(end_ym[:4]),   int(end_ym[4:])
    while (y, m) <= (ey, em):
        last = monthrange(y, m)[1]
        yield f"{y:04d}{m:02d}01", f"{y:04d}{m:02d}{last:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


def load_done() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    done = set()
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OK:"):
            done.add(line[3:].strip())
    return done


def log_done(bidid: str):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"OK:{bidid}\n")


# ── 목록 페이지 조작 ──────────────────────────────────────────────────────────

async def set_date_and_search(page, start: str, end: str) -> int:
    """날짜 변경 후 조회. list_link 수 반환."""
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
        await page.wait_for_selector("a.list_link", timeout=30_000)
    except PWTimeout:
        return 0

    # 페이지 크기 100으로
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
        try:
            await page.wait_for_selector("a.list_link", state="detached", timeout=5_000)
        except PWTimeout:
            pass
        try:
            await page.wait_for_selector("a.list_link", timeout=15_000)
        except PWTimeout:
            pass

    return await page.locator("a.list_link").count()


async def get_links_on_page(page) -> list[tuple[str, str]]:
    """현재 목록 페이지의 (bidid, href) 리스트 반환."""
    hrefs = await page.evaluate("""
        () => Array.from(document.querySelectorAll('a.list_link'))
                   .map(a => a.getAttribute('href') || '')
    """)
    result = []
    for href in hrefs:
        m = re.search(r"bidid=([^&]+)", href)
        if m:
            result.append((m.group(1), href))
    return result


async def go_next_page(page) -> bool:
    """목록/상세 공통 다음 페이지 이동."""
    for sel in ["a.next:not(.disabled)", ".paging a.next",
                "li.next:not(.disabled) a", "a[title='다음']", "button[title='다음']"]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.click()
            await page.wait_for_timeout(1_000)
            return True

    current = await page.evaluate("""
        () => {
            var el = document.querySelector('.paging .active, .paging .on, .pagination .active');
            return el ? parseInt(el.innerText.trim()) : null;
        }
    """)
    if current:
        moved = await page.evaluate(
            f"() => {{ if (typeof goPage==='function') {{ goPage({current + 1}); return true; }} return false; }}"
        )
        if moved:
            await page.wait_for_timeout(1_000)
            return True

    return False


# ── 다운로드 ──────────────────────────────────────────────────────────────────

async def wait_for_new_file(since: float, timeout: int = 60) -> Path | None:
    """DOWNLOAD_DIR 에서 since 이후 생성된 xls/xlsx 반환."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        await asyncio.sleep(0.5)
        for f in list(DOWNLOAD_DIR.glob("*.xls")) + list(DOWNLOAD_DIR.glob("*.xlsx")):
            if f.name.endswith(".crdownload"):
                continue
            if f.stat().st_mtime >= since:
                return f
    return None


async def click_download_btn(popup) -> bool:
    """엑셀 다운로드 버튼 클릭. 성공 여부 반환."""
    # info21c_pager 와 동일 셀렉터 우선
    for sel in [
        "span[name='excelSave']",
        "span[name='excelSaveBtn']",
        "button:has-text('엑셀')",
        "a:has-text('엑셀다운로드')",
    ]:
        loc = popup.locator(sel)
        if await loc.count() > 0:
            await loc.first.click()
            await popup.wait_for_timeout(1_500)
            # 확인 모달 처리
            if await popup.locator(".modal.in, .modal[style*='display: block']").count() > 0:
                for msel in ["button:has-text('확인')", ".modal .btn-primary", ".modal button[type='submit']"]:
                    ml = popup.locator(msel)
                    if await ml.count() > 0:
                        await ml.first.click()
                        break
            return True
    return False


# ── 상세 페이지 처리 ──────────────────────────────────────────────────────────

async def download_participants(popup, bidid: str, context) -> int:
    """
    참여자 상세 팝업에서 모든 페이지 다운로드.
    반환값: 다운로드한 파일 수
    """
    # CDP 다운로드 경로 설정
    cdp = await context.new_cdp_session(popup)
    await cdp.send("Page.setDownloadBehavior", {
        "behavior":     "allow",
        "downloadPath": str(DOWNLOAD_DIR.absolute()),
    })

    # 페이지 크기 100으로
    await popup.evaluate("""
        () => {
            var sel = document.querySelector('select[name=pageSize]');
            if (sel && sel.value !== '100') {
                sel.value = '100';
                sel.dispatchEvent(new Event('change', {bubbles:true}));
            }
        }
    """)
    await popup.wait_for_timeout(800)

    # 엑셀 저장은 전체 목록을 한 번에 내보내므로 1회만 다운로드
    click_time = time.time() - 1
    ok = await click_download_btn(popup)
    if not ok:
        print("    ⚠ 다운로드 버튼 찾기 실패")
        return 0

    new_file = await wait_for_new_file(click_time)
    if not new_file:
        print("    ⚠ 파일 감지 실패")
        return 0

    save_name = f"participants_{bidid}_1{new_file.suffix}"
    new_file.replace(DOWNLOAD_DIR / save_name)
    print(f"    → {save_name}")
    return 1


# ── 월 단위 처리 ──────────────────────────────────────────────────────────────

async def collect_all_links(page) -> list[tuple[str, str]]:
    """현재 검색 결과 전 페이지의 (bidid, href) 수집."""
    all_links = []
    list_page = 1
    while True:
        links = await get_links_on_page(page)
        print(f"  [목록 {list_page}p] {len(links)}건 수집")
        all_links.extend(links)
        if len(links) < 100:
            break
        if not await go_next_page(page):
            break
        list_page += 1
    return all_links


async def process_month(
    page, context, start: str, end: str, done: set[str]
) -> tuple[int, int]:
    label = f"{start[:4]}.{start[4:6]}"
    print(f"\n{'='*50}")
    print(f"[{label}] 날짜 설정 중...")

    count = await set_date_and_search(page, start, end)
    if count == 0:
        print("  → 결과 없음")
        return 0, 0

    # 1단계: 해당 월 링크 전부 수집
    all_links = await collect_all_links(page)
    print(f"  총 {len(all_links)}건")

    # base URL 추출 (예: https://infose.info21c.net)
    from urllib.parse import urlparse
    parsed = urlparse(page.url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    total_done = total_skip = 0

    # 2단계: 각 상세 URL로 직접 이동
    for idx, (bidid, href) in enumerate(all_links, 1):
        if bidid in done:
            total_skip += 1
            continue

        print(f"  [{idx}/{len(all_links)}] {bidid}")
        full_url = base_url + href if href.startswith("/") else href

        try:
            await page.goto(full_url, wait_until="domcontentloaded", timeout=20_000)

            n = await download_participants(page, bidid, context)
            if n > 0:
                log_done(bidid)
                done.add(bidid)
                total_done += 1
                print(f"    → 완료 ({n}파일)")
            else:
                print(f"    ⚠ 다운로드 0건")

        except Exception as e:
            print(f"    ⚠ 오류: {str(e)[:100]}")

        await page.wait_for_timeout(300)

    return total_done, total_skip


# ── 메인 ──────────────────────────────────────────────────────────────────────

async def run(type_name: str, start_ym: str, end_ym: str) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    done = load_done()
    print(f"이미 완료: {len(done)}건")
    print(f"저장 경로: {DOWNLOAD_DIR}")

    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            print("브라우저 연결 실패. Brave를 디버그 포트로 실행했는지 확인하세요:")
            print('  & "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe" --remote-debugging-port=9222')
            return

        # Info21c 탭 찾기
        page = context = None
        for ctx in browser.contexts:
            for p in ctx.pages:
                if "info21c" in p.url:
                    page, context = p, ctx
                    break
            if page:
                break

        if page is None:
            context = browser.contexts[0]
            page    = context.pages[0]
            print(f"  ⚠ Info21c 탭 미감지. 현재 탭 사용: {page.url}")

        print(f"  연결된 탭: {page.url}")

        # 목록 페이지로 복귀하는 함수
        async def ensure_list_page():
            for _ in range(10):
                has_search = await page.locator("#config_from_date").count() > 0
                if has_search:
                    return True
                try:
                    await page.go_back(wait_until="domcontentloaded", timeout=10_000)
                    await page.wait_for_timeout(500)
                except Exception:
                    break

            # 자동으로 못 찾으면 사용자가 직접 이동할 때까지 대기
            if await page.locator("#config_from_date").count() == 0:
                print("\n⚠ 날짜 설정 페이지를 찾을 수 없습니다.")
                print("  브라우저에서 Info21c 낙찰결과 검색 목록 페이지로 직접 이동해 주세요.")
                print("  (페이지 이동 후 자동으로 계속됩니다...)")
                while await page.locator("#config_from_date").count() == 0:
                    await asyncio.sleep(2)
                print("  → 페이지 감지됨. 계속합니다.")
            return True

        # 시작 전 목록 페이지 확인
        ok = await ensure_list_page()
        if not ok:
            print("⚠ 목록 페이지를 찾을 수 없습니다. 브라우저에서 Info21c 검색 목록 페이지로 이동 후 재실행하세요.")
            return

        months = list(iter_months(start_ym, end_ym))
        print(f"총 {len(months)}개월 처리 예정")

        grand_done = grand_skip = 0
        for i, (start, end) in enumerate(months, 1):
            print(f"\n진행: {i}/{len(months)}")
            await ensure_list_page()
            d, s = await process_month(page, context, start, end, done)
            grand_done += d
            grand_skip += s

        print(f"\n{'='*50}")
        print(f"완료: {grand_done}건 다운로드 / {grand_skip}건 스킵")


def main():
    parser = argparse.ArgumentParser(description="Info21c 참여자 데이터 수집")
    parser.add_argument("--type",  required=True, choices=["건축", "조경"], help="공종")
    parser.add_argument("--start", required=True, help="시작 월 YYYYMM (예: 202301)")
    parser.add_argument("--end",   required=True, help="종료 월 YYYYMM (예: 202603)")
    args = parser.parse_args()

    asyncio.run(run(args.type, args.start, args.end))


if __name__ == "__main__":
    main()
