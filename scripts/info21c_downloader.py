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
) -> None:
    """
    공사낙찰 목록 페이지에서 검색 조건 설정.
    start_date/end_date: YYYYMMDD 형식
    license_type: '0002' 또는 '0023'
    """
    # 공종 코드 → Info21c select value 매핑
    LICENSE_CODE_MAP = {"0002": "C081", "0023": "C084"}  # C081=실내건축[대], C084=조경[대]

    print(f"[2/4] 검색 조건 설정 중... (기간: {start_date}~{end_date}, 공종: {license_type})")

    await page.goto(LIST_URL, wait_until="networkidle")

    # ── 날짜 입력 (#from_date, #to_date / YYYY-MM-DD 형식) ────────────────────
    fmt_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    fmt_end   = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

    # 화면에 보이는 날짜 필드는 #config_from_date / #config_to_date
    await page.fill("#config_from_date", fmt_start)
    await page.keyboard.press("Escape")
    await page.fill("#config_to_date", fmt_end)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(300)

    actual_start = await page.input_value("#config_from_date")
    actual_end   = await page.input_value("#config_to_date")
    print(f"  → 날짜 설정: {actual_start} ~ {actual_end}")

    # ── 공종 선택 (#search_code1 셀렉트박스) ──────────────────────────────────
    code_val = LICENSE_CODE_MAP.get(license_type, "C081")
    await page.select_option("#search_code1", value=code_val)
    print(f"  → 공종 선택: {code_val} ({LICENSE_TYPES.get(license_type)})")

    # ── 조회 버튼 (#topSearchBtn) ─────────────────────────────────────────────
    await page.click("#topSearchBtn")

    # 결과 테이블 행이 실제로 로드될 때까지 대기 (AJAX 응답 완료 확인)
    try:
        await page.wait_for_selector("table tbody tr[data-key]", timeout=TIMEOUT)
        row_count = await page.locator("table tbody tr[data-key]").count()
        print(f"  → 검색 완료 ({row_count}건 로드됨)")
    except PWTimeout:
        print("  ⚠ 결과 로딩 타임아웃. 결과가 없거나 느린 응답입니다.")

    if debug:
        print("  검색 결과를 확인 후 Enter를 누르세요.")
        input("  [Enter 계속]")


# ── 엑셀 내보내기 ─────────────────────────────────────────────────────────────
async def export_csv(page, download_dir: Path, license_type: str, start_date: str, end_date: str, debug: bool = False) -> Path:
    """엑셀 버튼 클릭 → 다이얼로그 처리 → 파일 다운로드."""
    print("[3/4] 엑셀 내보내기 중...")

    download_dir.mkdir(parents=True, exist_ok=True)
    # 다운로드 파일명 (확장자는 실제 다운로드 후 결정)
    output_stem = download_dir / f"info21c_{license_type}_{start_date}_{end_date}"

    # ── 엑셀 버튼 클릭: span[name='excelSaveBtn'] ─────────────────────────────
    await page.wait_for_selector("span[name='excelSaveBtn']", timeout=TIMEOUT)
    await page.click("span[name='excelSaveBtn']")
    await page.wait_for_timeout(1000)

    # ── 다이얼로그가 열렸는지 확인 ────────────────────────────────────────────
    # bids.js가 모달을 열 수도 있고 직접 다운로드할 수도 있음
    # 모달이 열렸으면 옵션 설정 후 다운로드, 없으면 바로 다운로드 대기
    modal_visible = await page.locator(".modal.in, .modal[style*='display: block'], .modal[style*='display:block']").count() > 0

    if modal_visible:
        print("  → 내보내기 다이얼로그 감지됨")
        if debug:
            print("  다이얼로그 옵션을 확인/설정 후 Enter를 누르세요.")
            input("  [Enter 계속]")
        # 다이얼로그 내 다운로드 버튼 클릭
        async with page.expect_download(timeout=60_000) as dl_info:
            for sel in ["button:has-text('확인')", "button:has-text('다운로드')",
                        ".modal button[type='submit']", ".modal .btn-primary"]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click()
                    break
    else:
        # 다이얼로그 없이 바로 다운로드 시작
        print("  → 직접 다운로드 시작")
        async with page.expect_download(timeout=60_000) as dl_info:
            pass  # 이미 클릭됨

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
) -> Path:
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
            await set_search_filters(page, start_date, end_date, license_type, debug=debug)
            path = await export_csv(page, DOWNLOAD_DIR, license_type, start_date, end_date, debug=debug)
            return path
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
        path = await run_download(
            start_date=args.start,
            end_date=args.end,
            license_type=lt,
            headless=args.headless,
            debug=args.debug,
            user_id=args.id,
            password=args.pw,
            use_brave=args.brave,
        )
        downloaded_files.append(path)

    print(f"\n=== 다운로드 완료 ===")
    for f in downloaded_files:
        print(f"  {f}")
    print("\n다음 단계: python scripts/etl_csv.py --file <경로>")


if __name__ == "__main__":
    asyncio.run(main())
