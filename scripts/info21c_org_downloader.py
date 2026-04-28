"""
Info21c 발주처별 낙찰 데이터 다운로드 스크립트.

발주처명(search_org)으로 필터링해 전체 기간 데이터를 가져온다.
100건 한계 도달 시 연도 단위로 자동 분할한다.

개선사항:
  - 브라우저 세션을 전체 실행 동안 재사용 (발주처마다 재로그인 없음)
  - DB에 이미 있는 기간은 다운로드 건너뜀 (스마트 재개)

사용법:
  # DB 상위 발주처 자동 추출 후 다운로드
  python scripts/info21c_org_downloader.py --top 30

  # 특정 발주처
  python scripts/info21c_org_downloader.py --org "화성시" --type 0023
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.info21c_downloader import (
    LOGIN_URL, LIST_URL, DOWNLOAD_DIR, LICENSE_TYPES, TIMEOUT,
    login, export_csv,
)
from scripts.etl_csv import extract_and_transform, load_to_db

DEFAULT_ID = os.getenv("INFO21C_ID", "nw8856")
DEFAULT_PW = os.getenv("INFO21C_PW", "nw8856")

YEARS = list(range(2020, 2027))   # 다운로드 대상 연도 범위


# ── 세션 만료 감지 및 재로그인 ────────────────────────────────────────────────
async def ensure_logged_in(page, user_id: str, password: str):
    """현재 페이지가 로그인 상태인지 확인하고, 세션 만료 시 재로그인."""
    current_url = page.url
    if "login" in current_url or current_url == "about:blank":
        print("  세션 만료 감지 -> 재로그인...")
        await login(page, user_id, password)


# ── DB에서 해당 발주처+기간 데이터 존재 여부 확인 ────────────────────────────
async def has_data_in_db(org_keyword: str, license_type: str, start_date: str, end_date: str) -> bool:
    """
    DB에 해당 발주처 키워드 + 공종 + 기간 데이터가 존재하면 True.
    발주처 키워드는 client_name LIKE '%keyword%' 로 검색.
    """
    from datetime import date
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import text

    project_type = "조경" if license_type == "0023" else "실내건축"
    start_dt = date(int(start_date[:4]), int(start_date[4:6]), int(start_date[6:]))
    end_dt   = date(int(end_date[:4]),   int(end_date[4:6]),   int(end_date[6:]))

    async with AsyncSessionLocal() as db:
        r = await db.scalar(text("""
            SELECT COUNT(*) FROM bids_history h
            JOIN bid_license_types l ON l.project_id = h.project_id
            WHERE h.client_name LIKE :kw
              AND l.type_name = :pt
              AND h.bid_date BETWEEN :sd AND :ed
        """), {"kw": f"%{org_keyword}%", "pt": project_type, "sd": start_dt, "ed": end_dt})
    return (r or 0) > 0


# ── 검색 조건 설정 (발주처 필터 추가) ─────────────────────────────────────────
async def set_filters_with_org(
    page,
    start_date: str,
    end_date: str,
    license_type: str,
    org_keyword: str,
) -> int:
    """
    공종 + 날짜 + 발주처 키워드로 검색 후 로드된 행 수 반환.
    start_date/end_date: YYYYMMDD 형식
    org_keyword: 발주처명 부분 일치 키워드 (예: '화성시')
    """
    LICENSE_CODE_MAP = {"0002": "C081", "0023": "C084"}
    code_val = LICENSE_CODE_MAP.get(license_type, "C081")

    fmt_s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    fmt_e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

    await page.goto(LIST_URL, wait_until="networkidle")

    # 필수 요소가 로드될 때까지 대기
    try:
        await page.wait_for_selector("#config_from_date", timeout=15_000)
    except PWTimeout:
        print("  페이지 로드 실패 (networkidle 후에도 요소 없음)")
        return 0

    await page.evaluate(
        "(args) => {"
        "  var fd=document.querySelector('#config_from_date'); if(fd) fd.value=args[0];"
        "  var td=document.querySelector('#config_to_date');   if(td) td.value=args[1];"
        "  var cs=document.querySelector('#search_code1');"
        "  if(cs){cs.value=args[2]; cs.dispatchEvent(new Event('change',{bubbles:true}));}"
        "  var org=document.querySelector('input[name=search_org]');"
        "  if(org) org.value=args[3];"
        "}",
        [fmt_s, fmt_e, code_val, org_keyword],
    )
    await page.wait_for_timeout(400)

    await page.click("#topSearchBtn")

    try:
        await page.wait_for_selector("table tbody tr[data-key]", timeout=TIMEOUT)
    except PWTimeout:
        return 0  # 결과 없음

    # 페이지 크기 100
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

    return await page.locator("table tbody tr[data-key]").count()


# ── 단일 기간 다운로드 ────────────────────────────────────────────────────────
async def download_org_period(
    page,
    start_date: str,
    end_date: str,
    license_type: str,
    org_keyword: str,
    output_stem: Path,
) -> tuple[Path | None, int]:
    """
    발주처 키워드 + 기간으로 1회 다운로드.
    Returns: (저장 경로, 행 수)  — 결과 없으면 (None, 0)
    """
    try:
        row_count = await set_filters_with_org(
            page, start_date, end_date, license_type, org_keyword
        )
    except Exception as e:
        print(f"    필터 설정 오류: {e}")
        return None, 0

    if row_count == 0:
        return None, 0

    try:
        async with page.expect_download(timeout=60_000) as dl_info:
            await page.click("span[name='excelSaveBtn']")
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

        dl = await dl_info.value
        suffix = Path(dl.suggested_filename).suffix or ".xlsx"
        output_path = output_stem.with_suffix(suffix)
        await dl.save_as(str(output_path))
        return output_path, row_count
    except Exception as e:
        print(f"    다운로드 실패: {e}")
        return None, 0


# ── 발주처 1개 전체 수집 ──────────────────────────────────────────────────────
async def collect_org(
    page,
    org_keyword: str,
    license_type: str,
    user_id: str,
    password: str,
) -> dict:
    """
    발주처 키워드로 전체 기간(YEARS) 데이터를 수집하고 DB에 적재.
    100건 한계 도달 시 연도 단위로 분할.
    page: 외부에서 전달받은 재사용 페이지 객체
    """
    label = f"{org_keyword} / {LICENSE_TYPES[license_type]}"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    total_inserted = 0
    total_skipped  = 0

    # 세션 만료 시 재로그인
    await ensure_logged_in(page, user_id, password)

    # 전체 기간 한 번에 시도 (2020~2026)
    full_start = f"{YEARS[0]}0101"
    full_end   = f"{YEARS[-1]}1231"
    stem = DOWNLOAD_DIR / f"org_{license_type}_{org_keyword}_{full_start}_{full_end}"
    print(f"  [{label}] 전체 기간 시도...")
    path, cnt = await download_org_period(page, full_start, full_end, license_type, org_keyword, stem)

    if cnt == 0:
        print(f"  [{label}] 결과 없음")
        return {"label": label, "inserted": 0, "skipped": 0}

    periods = []
    if cnt >= 100:
        print(f"  [{label}] {cnt}건 -> 연도 단위 분할")
        if path and path.exists():
            path.unlink()
        for year in YEARS:
            y_start = f"{year}0101"
            y_end   = f"{year}1231"

            # 스마트 재개: DB에 이미 있으면 건너뜀
            if await has_data_in_db(org_keyword, license_type, y_start, y_end):
                print(f"    {year}년 -> DB에 이미 있음, 건너뜀")
                continue

            ystem = DOWNLOAD_DIR / f"org_{license_type}_{org_keyword}_{y_start}_{y_end}"
            ypath, ycnt = await download_org_period(page, y_start, y_end, license_type, org_keyword, ystem)
            if ycnt >= 100:
                print(f"    {year}년 {ycnt}건 -> 여전히 한계. 반기 분할")
                if ypath and ypath.exists():
                    ypath.unlink()
                for half_s, half_e in [(f"{year}0101", f"{year}0630"),
                                       (f"{year}0701", f"{year}1231")]:
                    # 스마트 재개: 반기도 확인
                    if await has_data_in_db(org_keyword, license_type, half_s, half_e):
                        print(f"      {half_s[:6]} -> DB에 이미 있음, 건너뜀")
                        continue
                    hstem = DOWNLOAD_DIR / f"org_{license_type}_{org_keyword}_{half_s}_{half_e}"
                    hpath, hcnt = await download_org_period(page, half_s, half_e, license_type, org_keyword, hstem)
                    if hpath:
                        periods.append(hpath)
            elif ypath:
                periods.append(ypath)
    else:
        periods = [path]

    # ETL 적재
    for fpath in periods:
        if not fpath or not fpath.exists():
            continue
        try:
            df = extract_and_transform(fpath)
            ins, skip = await load_to_db(df)
            total_inserted += ins
            total_skipped  += skip
        except Exception as e:
            print(f"    ETL 실패 {fpath.name}: {e}")

    print(f"  [{label}] 완료: 신규 {total_inserted}건 / 스킵 {total_skipped}건")
    return {"label": label, "inserted": total_inserted, "skipped": total_skipped}


# ── 메인 ──────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Info21c 발주처별 데이터 수집")
    parser.add_argument("--org",  help="발주처 키워드 (예: 화성시)")
    parser.add_argument("--top",  type=int, default=0, help="DB 상위 N개 발주처 자동 수집")
    parser.add_argument("--type", choices=["0002", "0023", "all"], default="all")
    parser.add_argument("--id",   default=DEFAULT_ID)
    parser.add_argument("--pw",   default=DEFAULT_PW)
    args = parser.parse_args()

    types = list(LICENSE_TYPES.keys()) if args.type == "all" else [args.type]

    # 발주처 목록 결정
    orgs = []
    if args.org:
        orgs = [args.org]
    elif args.top > 0:
        from app.db.session import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            r = await db.execute(text(f"""
                SELECT client_name FROM bids_history
                WHERE client_name IS NOT NULL
                GROUP BY client_name
                ORDER BY COUNT(*) DESC
                LIMIT {args.top}
            """))
            orgs = [row[0] for row in r.fetchall() if row[0]]
        # 키워드 축약: '경기도 화성시 공원녹지사업소' -> '화성시 공원녹지'
        orgs = [o.replace("경기도 ", "").replace("서울특별시 ", "").replace("인천광역시 ", "") for o in orgs]
        orgs = [o[:10] for o in orgs]  # 10자 이내로 축약
    else:
        parser.print_help()
        return

    print(f"=== 발주처별 수집 시작: {orgs} ===\n")

    total = 0

    # 브라우저를 한 번만 열고 전체 발주처에 재사용
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        try:
            print(f"로그인 중... ({LOGIN_URL})")
            await login(page, args.id, args.pw)

            for org in orgs:
                for lt in types:
                    result = await collect_org(page, org, lt, args.id, args.pw)
                    total += result.get("inserted", 0)
                    await asyncio.sleep(1)

        finally:
            await browser.close()

    print(f"\n=== 완료 / 총 신규 적재: {total}건 ===")


if __name__ == "__main__":
    asyncio.run(main())
