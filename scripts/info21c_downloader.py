"""
Info21c 공사낙찰 데이터 자동 다운로드 스크립트.

사용법:
  # 기간 지정 (기본: 실내건축 0002 + 조경 0023 모두)
  python scripts/info21c_downloader.py --start 20250101 --end 20251231

  # 공종 지정
  python scripts/info21c_downloader.py --start 20250101 --end 20251231 --type 0002

  # 헤드리스 (화면 없이)
  python scripts/info21c_downloader.py --start 20250101 --end 20251231 --headless

  # 첫 실행 시 (브라우저 열어서 단계 확인)
  python scripts/info21c_downloader.py --start 20250101 --end 20250131 --debug

사전 설치:
  pip install playwright
  playwright install chromium

다운로드 결과:
  data/downloads/info21c_{type}_{start}_{end}.csv
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Download, TimeoutError as PWTimeout

# ── 설정 ──────────────────────────────────────────────────────────────────────
LOGIN_URL   = "https://www.info21c.net/info21c/member/login/index"
# 공사낙찰 목록 (bidtype=con: 공사, bid_suc=suc: 낙찰)
LIST_URL    = "https://infose.info21c.net/info21c/bids/list?bidtype=con&bid_suc=suc"

# 목록 한 페이지당 행 수. 엑셀 내보내기가 현재 페이지만 내보내므로
# 이 값이 곧 "한 파일에 담기는 최대 건수" 다.
PAGE_SIZE   = 100

DEFAULT_ID  = os.getenv("INFO21C_ID", "nw8856")
DEFAULT_PW  = os.getenv("INFO21C_PW", "nw8856")

DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "downloads"

# 공종 코드 → 이름
LICENSE_TYPES = {"0002": "실내건축", "0023": "조경"}

TIMEOUT = 30_000  # ms


# ── 로그인 ────────────────────────────────────────────────────────────────────
async def login(page, user_id: str, password: str, debug: bool = False) -> None:
    print(f"[1/4] 로그인 중... ({LOGIN_URL})")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")

    # 로그인 폼이 렌더링될 때까지 대기 (최대 10초)
    try:
        await page.wait_for_selector("input[name='id']", timeout=10_000)
    except PWTimeout:
        pass

    # ID 입력
    id_filled = False
    for sel in ["input[name='id']", "#id", "input[placeholder='아이디']"]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.fill(user_id)
            id_filled = True
            break

    # PW 입력
    pw_filled = False
    for sel in ["input[name='pass']", "#pass", "input[placeholder='비밀번호']"]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.fill(password)
            pw_filled = True
            break

    if not id_filled or not pw_filled:
        if debug:
            print("  ⚠ 로그인 필드를 찾지 못했습니다. 브라우저에서 직접 로그인 후 Enter를 누르세요.")
            input("  [Enter 계속]")
            # 수동 로그인 완료 → 버튼 클릭 스킵하고 바로 성공 확인
            await page.wait_for_load_state("networkidle")
            print(f"  → 로그인 성공 (현재 URL: {page.url})")
            return
        else:
            raise RuntimeError("로그인 폼 필드를 찾을 수 없습니다. --debug 모드로 다시 실행하세요.")

    # 로그인 버튼 (#login_btn 확정)
    await page.click("#login_btn")
    await page.wait_for_load_state("networkidle")

    # 로그인 실패 감지
    if "login" in page.url.lower() or "member" in page.url.lower():
        raise RuntimeError(f"로그인 실패 (URL: {page.url}). 아이디/비밀번호를 확인하세요.")

    print(f"  → 로그인 성공 (현재 URL: {page.url})")


# ── 검색 조건 설정 ─────────────────────────────────────────────────────────────
async def set_search_filters(
    page,
    start_date: str,
    end_date: str,
    license_type: str,
    debug: bool = False,
) -> int:
    """
    공사낙찰 목록 페이지에서 검색 조건 설정.
    start_date/end_date: YYYYMMDD 형식
    license_type: '0002' 또는 '0023'

    Returns:
        현재 페이지에 로드된 결과 행 수. 호출부가 페이지 넘김 여부를 판단한다.
    """
    # 공종 코드 → Info21c 체크박스 value 매핑
    LICENSE_CODE_MAP = {"0002": "C002", "0023": "C084"}  # C002=실내건축, C084=조경

    print(f"[2/4] 검색 조건 설정 중... (기간: {start_date}~{end_date}, 공종: {license_type})")

    await page.goto(LIST_URL, wait_until="networkidle")

    # ── 날짜 입력 (#config_from_date / #config_to_date) ───────────────────────
    # playwright fill()은 datepicker에 의해 무시됨 → JS 직접 주입 방식 사용
    fmt_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    fmt_end   = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

    await page.evaluate(
        "(args) => { "
        "  document.querySelector('[name=config_from_date]').value = args[0]; "
        "  document.querySelector('[name=config_to_date]').value   = args[1]; "
        "}",
        [fmt_start, fmt_end]
    )
    await page.wait_for_timeout(300)

    actual_start = await page.input_value("[name=config_from_date]")
    actual_end   = await page.input_value("[name=config_to_date]")
    print(f"  → 날짜 설정: {actual_start} ~ {actual_end}")

    # ── 공종 선택 (itemcode 체크박스) ─────────────────────────────────────────
    # 전체 해제 후 해당 공종 하나만 체크
    code_val = LICENSE_CODE_MAP.get(license_type, "C002")
    await page.evaluate(
        "(val) => { "
        "  document.querySelectorAll('input[name=itemcode]').forEach(cb => { cb.checked = false; }); "
        "  var target = document.querySelector('input[name=itemcode][value=\"' + val + '\"]'); "
        "  if (target) { target.checked = true; target.dispatchEvent(new Event('change', {bubbles: true})); } "
        "}",
        code_val
    )
    await page.wait_for_timeout(300)
    print(f"  → 공종 선택: {code_val} ({LICENSE_TYPES.get(license_type)})")

    # ── 조회 버튼 (#config_search_btn) ───────────────────────────────────────
    await page.click("#config_search_btn")

    # 결과 테이블 행이 실제로 로드될 때까지 대기 (AJAX 응답 완료 확인)
    try:
        await page.wait_for_selector("a.list_link", timeout=TIMEOUT)
    except PWTimeout:
        print("  [!] 결과 로딩 타임아웃. 결과가 없거나 느린 응답입니다.")
        return 0

    # ── 페이지 크기를 PAGE_SIZE 로 변경 (기본 15) ────────────────────────────
    # run_download 가 "행 수 < PAGE_SIZE 면 마지막 페이지" 로 판단하므로
    # 여기서 실제로 설정한 값과 그 상수가 반드시 같아야 한다.
    changed = await page.evaluate("""
        (size) => {
            var sel = document.querySelector('select[name=pageSize]');
            if (!sel) return false;
            sel.value = String(size);
            sel.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }
    """, PAGE_SIZE)
    if changed:
        await page.wait_for_timeout(1500)

    row_count = await page.locator("a.list_link").count()
    print(f"  → 검색 완료 ({row_count}건 로드됨)")

    if debug:
        print("  검색 결과를 확인 후 Enter를 누르세요.")
        input("  [Enter 계속]")

    return row_count


# ── 페이지 넘김 ───────────────────────────────────────────────────────────────
async def goto_next_page(page) -> bool:
    """다음 페이지로 이동. 더 없으면 False.

    엑셀 내보내기는 **현재 페이지만** 내보낸다. pageSize=100 으로 키워도 결과가
    100건을 넘으면 나머지가 조용히 잘린다 — 2026-05-31 부터 고아 참여자
    (bid_participants 는 있는데 bids_history 가 없는 공고)가 쌓인 원인이 이것이다.
    실측: 실내건축 2026-08-29~09-09 은 123건인데 목록은 100건에서 끊겼다.

    `info21c_participants.py::search_and_collect_links` 와 같은 방식이다.
    거기는 진작 전 페이지를 순회하고 있었고 이쪽만 빠져 있었다.
    """
    moved = await page.evaluate(r"""
        () => {
            var items = Array.from(document.querySelectorAll('ul.pagination li.page-item'));
            var cur = items.find(li =>
                li.classList.contains('disabled') && /^\d+$/.test(li.innerText.trim())
            );
            if (cur) {
                var curNum = parseInt(cur.innerText.trim());
                var next = items.find(li =>
                    !li.classList.contains('disabled') &&
                    parseInt(li.innerText.trim()) === curNum + 1
                );
                if (next) { next.querySelector('a').click(); return true; }
            }
            var last = items[items.length - 1];
            if (last && !last.classList.contains('disabled')) {
                last.querySelector('a').click();
                return true;
            }
            return false;
        }
    """)
    if not moved:
        return False
    await page.wait_for_selector("a.list_link", timeout=15_000)
    await page.wait_for_timeout(800)
    return True


# ── 엑셀 내보내기 ─────────────────────────────────────────────────────────────
async def export_csv(page, download_dir: Path, license_type: str, start_date: str, end_date: str,
                     debug: bool = False, page_num: int = 1) -> Path:
    """엑셀 버튼 클릭 → 다이얼로그 처리 → 파일 다운로드.

    page_num 이 2 이상이면 파일명에 `_p{n}` 을 붙인다. 1페이지는 기존 파일명을
    유지해야 이미 받아둔 파일·문서의 경로가 그대로 통한다.
    """
    print(f"[3/4] 엑셀 내보내기 중... ({page_num}페이지)")

    download_dir.mkdir(parents=True, exist_ok=True)
    # 다운로드 파일명 (확장자는 실제 다운로드 후 결정)
    suffix_pg = "" if page_num <= 1 else f"_p{page_num}"
    output_stem = download_dir / f"info21c_{license_type}_{start_date}_{end_date}{suffix_pg}"

    # ── 엑셀 버튼 클릭 + 다운로드 대기 ──────────────────────────────────────
    # expect_download는 반드시 클릭 이전에 열어야 다운로드 이벤트를 놓치지 않음
    await page.wait_for_selector("button[name='list_excel_btn']", timeout=TIMEOUT)

    async with page.expect_download(timeout=60_000) as dl_info:
        await page.click("button[name='list_excel_btn']")

        # 클릭 후 모달이 열리는 경우 → 모달 내 확인 버튼 클릭
        await page.wait_for_timeout(1500)
        modal_visible = await page.locator(
            ".modal.in, .modal[style*='display: block'], .modal[style*='display:block']"
        ).count() > 0

        if modal_visible:
            print("  → 내보내기 다이얼로그 감지됨")
            if debug:
                print("  다이얼로그 옵션을 확인/설정 후 Enter를 누르세요.")
                input("  [Enter 계속]")
            for sel in ["button:has-text('확인')", "button:has-text('다운로드')",
                        ".modal button[type='submit']", ".modal .btn-primary"]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click()
                    break
        else:
            print("  → 직접 다운로드 시작")

    download: Download = await dl_info.value
    # 실제 파일명 확장자 사용 (.xlsx 또는 .csv)
    suffix = Path(download.suggested_filename).suffix or ".xlsx"
    output_path = output_stem.with_suffix(suffix)
    await download.save_as(str(output_path))
    print(f"  → 저장 완료: {output_path}")
    return output_path


# ── 메인 ──────────────────────────────────────────────────────────────────────
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"


async def run_download(
    start_date: str,
    end_date: str,
    license_type: str,
    headless: bool,
    debug: bool,
    user_id: str,
    password: str,
    use_brave: bool = False,
) -> list[Path]:
    async with async_playwright() as pw:
        launch_kwargs = dict(headless=headless)
        if use_brave and Path(BRAVE_PATH).exists():
            launch_kwargs["executable_path"] = BRAVE_PATH
            print(f"  Brave 브라우저 사용: {BRAVE_PATH}")
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        try:
            await login(page, user_id, password, debug=debug)
            row_count = await set_search_filters(page, start_date, end_date, license_type, debug=debug)
            if row_count == 0:
                print("  → 결과 없음, 건너뜀")
                return []

            paths: list[Path] = []
            page_num = 1
            while True:
                paths.append(await export_csv(
                    page, DOWNLOAD_DIR, license_type, start_date, end_date,
                    debug=debug, page_num=page_num,
                ))
                # 현재 페이지가 꽉 차 있지 않으면 마지막 페이지다
                if row_count < PAGE_SIZE:
                    break
                if not await goto_next_page(page):
                    break
                page_num += 1
                row_count = await page.locator("a.list_link").count()
                print(f"  → {page_num}페이지 ({row_count}건)")
            return paths
        finally:
            if not debug:
                await browser.close()
            else:
                print("[4/4] 완료. 브라우저를 닫으려면 Enter를 누르세요.")
                input()
                await browser.close()


async def main():
    parser = argparse.ArgumentParser(description="Info21c 공사낙찰 데이터 자동 다운로드")
    parser.add_argument("--start",    required=True, help="시작일 YYYYMMDD (예: 20250101)")
    parser.add_argument("--end",      required=True, help="종료일 YYYYMMDD (예: 20251231)")
    parser.add_argument("--type",     choices=["0002", "0023", "all"], default="all",
                        help="공종: 0002=실내건축, 0023=조경, all=둘 다 (기본)")
    parser.add_argument("--headless", action="store_true", help="화면 없이 실행")
    parser.add_argument("--debug",    action="store_true", help="단계별 확인 모드 (자동화 불확실 시)")
    parser.add_argument("--brave",    action="store_true", help=f"Brave 브라우저 사용 ({BRAVE_PATH})")
    parser.add_argument("--id",       default=DEFAULT_ID, help="Info21c 아이디")
    parser.add_argument("--pw",       default=DEFAULT_PW, help="Info21c 비밀번호")
    args = parser.parse_args()

    # 날짜 유효성 검사
    try:
        datetime.strptime(args.start, "%Y%m%d")
        datetime.strptime(args.end,   "%Y%m%d")
    except ValueError:
        print("날짜 형식 오류: YYYYMMDD 형식으로 입력하세요.")
        sys.exit(1)

    types_to_run = list(LICENSE_TYPES.keys()) if args.type == "all" else [args.type]

    downloaded_files = []
    for lt in types_to_run:
        print(f"\n=== {LICENSE_TYPES[lt]} ({lt}) 다운로드 ===")
        paths = await run_download(
            start_date=args.start,
            end_date=args.end,
            license_type=lt,
            headless=args.headless,
            debug=args.debug,
            user_id=args.id,
            password=args.pw,
            use_brave=args.brave,
        )
        downloaded_files.extend(paths)

    print(f"\n=== 다운로드 완료 ({len(downloaded_files)}개 파일) ===")
    for f in downloaded_files:
        print(f"  {f}")
    print("\n다음 단계: 받은 파일을 **전부** 적재한다")
    for f in downloaded_files:
        print(f"  python scripts/etl_csv.py --file {f}")


if __name__ == "__main__":
    asyncio.run(main())
