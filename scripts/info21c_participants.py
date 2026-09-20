"""
Info21c 낙찰결과 참여자 데이터 수집 스크립트.

각 공고 상세 페이지에서:
  - bid_type / price_method 추출 → bids_history 업데이트
  - Excel 다운로드 → bid_participants 적재

사용법:
  python scripts/info21c_participants.py --start 20250101 --end 20250531 --type 0002
  python scripts/info21c_participants.py --start 20250101 --end 20250531 --type 0023

사전 조건:
  - info21c_downloader.py 로 목록 Excel 다운 및 bids_history 적재 완료
  - pip install playwright && playwright install chromium

저장 경로:
  data/participants/participants_{bidid}.xlsx
로그 파일:
  data/downloads/_participants_etl.log
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Download, TimeoutError as PWTimeout

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

LOGIN_URL    = "https://www.info21c.net/info21c/member/login/index"
LIST_URL     = "https://infose.info21c.net/info21c/bids/list?bidtype=con&bid_suc=suc"

DEFAULT_ID   = os.getenv("INFO21C_ID", "nw8856")
DEFAULT_PW   = os.getenv("INFO21C_PW", "nw8856")

DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "participants"
LOG_FILE     = Path(__file__).parent.parent / "data" / "downloads" / "_participants_etl.log"

LICENSE_TYPES    = {"0002": "실내건축", "0023": "조경"}
LICENSE_CODE_MAP = {"0002": "C002", "0023": "C084"}

TIMEOUT = 30_000


# ── 로그 ──────────────────────────────────────────────────────────────────────

def load_done() -> set[str]:
    if not LOG_FILE.exists():
        return set()
    done = set()
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("OK:"):
            done.add(line[3:].split()[0])
    return done


def log_result(bidid: str, status: str, detail: str = ""):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{status}:{bidid}  [{ts}] {detail}\n")


# ── 로그인 ────────────────────────────────────────────────────────────────────

async def login(page, user_id: str, password: str) -> None:
    print(f"[로그인] {LOGIN_URL}")
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
        raise RuntimeError(f"로그인 실패 (URL: {page.url})")
    print(f"  -> 로그인 성공")


# ── 목록 페이지 ───────────────────────────────────────────────────────────────

async def search_and_collect_links(
    page, start_date: str, end_date: str, license_type: str
) -> list[tuple[str, str]]:
    """검색 후 전체 페이지의 (info21c_bidid, href) 수집."""
    print(f"\n[검색] {start_date}~{end_date} / {LICENSE_TYPES.get(license_type)}")
    await page.goto(LIST_URL, wait_until="networkidle")

    # 날짜 입력
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

    # 공종 체크박스
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

    # 검색
    await page.click("#config_search_btn")
    try:
        await page.wait_for_selector("a.list_link", timeout=TIMEOUT)
    except PWTimeout:
        print("  -> 결과 없음")
        return []

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

    # 전체 페이지 링크 수집
    all_links: list[tuple[str, str]] = []
    page_num = 1
    while True:
        hrefs = await page.evaluate("""
            () => Array.from(document.querySelectorAll('a.list_link'))
                       .map(a => a.getAttribute('href') || '')
        """)
        for href in hrefs:
            # href 형태: /suc/view/con/250509183018223-00-00-01
            m = re.search(r"/suc/view/con/([^?&\"']+)", href)
            if m:
                bidid = m.group(1)
                full = f"https://cloud.info21c.net{href}" if href.startswith("/") else href
                all_links.append((bidid, full))

        print(f"  [목록 {page_num}p] {len(hrefs)}건")
        if len(hrefs) < 100:
            break

        # 다음 페이지 (ul.pagination li.page-item 방식)
        moved = await page.evaluate("""
            () => {
                var items = Array.from(document.querySelectorAll('ul.pagination li.page-item'));
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
                var last = items[items.length - 1];
                if (last && !last.classList.contains('disabled')) {
                    last.querySelector('a').click();
                    return true;
                }
                return false;
            }
        """)
        if not moved:
            break
        await page.wait_for_selector("a.list_link", timeout=15_000)
        await page.wait_for_timeout(500)
        page_num += 1

    print(f"  -> 총 {len(all_links)}건 수집")
    return all_links


# ── 상세 페이지 파싱 ──────────────────────────────────────────────────────────

async def parse_detail(page, url: str) -> dict | None:
    """
    상세 페이지에서 bid_type, price_method, g2b_notice_id 추출.
    유찰/기초금액 없음이면 skip 반환.
    """
    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    await page.wait_for_timeout(300)

    # 기초금액 0 체크 (민간 발주처 등)
    basic_val = await page.input_value("#basic")
    if not basic_val or float(basic_val or 0) == 0:
        return {"skip": True, "reason": "기초금액 없음(민간)"}

    # 유찰 체크
    is_yuchal = await page.locator(".alert-danger").count() > 0
    if is_yuchal:
        return {"skip": True, "reason": "유찰"}

    # G2B 공고번호
    g2b_notice_id = await page.evaluate("""
        () => {
            var rows = document.querySelectorAll('.basic table tbody tr');
            for (var r of rows) {
                var ths = r.querySelectorAll('th');
                for (var i = 0; i < ths.length; i++) {
                    if (ths[i].textContent.includes('공고번호')) {
                        var tds = r.querySelectorAll('td');
                        return tds[i] ? tds[i].textContent.trim() : null;
                    }
                }
            }
            return null;
        }
    """)

    # price_method: 개찰결과 섹션에 복수예가 테이블 있으면 복수예비가격
    has_multispare = await page.locator("div.multispare").count() > 0
    price_method = "복수예비가격" if has_multispare else "고정예정가격"

    # bid_type: 종합심사 안내문 or bidproc 값으로 판별
    is_jonghabjsim = await page.locator("text=종합심사낙찰제 공고입니다").count() > 0
    bidproc = await page.evaluate("() => { var el = document.getElementById('bidproc'); return el ? el.value : ''; }")

    if is_jonghabjsim:
        bid_type = "종합심사"
    elif bidproc == "N":
        bid_type = "최저가"
    elif bidproc == "T":
        bid_type = "협상"
    else:
        bid_type = "적격심사"

    return {
        "skip": False,
        "g2b_notice_id": g2b_notice_id,
        "bid_type": bid_type,
        "price_method": price_method,
    }


# ── Excel 다운로드 ────────────────────────────────────────────────────────────

async def download_excel(page, context, bidid: str) -> Path | None:
    """상세 페이지에서 엑셀저장 버튼 클릭 -> 파일 다운로드."""
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    for ext in (".xlsx", ".xls"):
        existing = DOWNLOAD_DIR / f"participants_{bidid}{ext}"
        if existing.exists():
            return existing

    try:
        async with page.expect_download(timeout=30_000) as dl_info:
            await page.click("button.excel-btn")
            await page.wait_for_timeout(1000)

            modal = page.locator(".modal.show, .modal[style*='display: block']")
            if await modal.count() > 0:
                for sel in ["button:has-text('확인')", ".modal .btn-primary"]:
                    btn = page.locator(sel)
                    if await btn.count() > 0:
                        await btn.first.click()
                        break

        dl: Download = await dl_info.value
        suffix = Path(dl.suggested_filename).suffix or ".xlsx"
        save_path = DOWNLOAD_DIR / f"participants_{bidid}{suffix}"
        await dl.save_as(str(save_path))
        return save_path

    except Exception as e:
        print(f"    [!] 다운로드 실패: {str(e)[:60]}")
        return None


# ── DB 업데이트 ───────────────────────────────────────────────────────────────

async def update_bid_type_and_method(project_id: str, bid_type: str, price_method: str) -> None:
    """bids_history의 bid_type, price_method 업데이트."""
    from app.db.session import AsyncSessionLocal
    from app.db.models import BidsHistory
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(BidsHistory).where(BidsHistory.project_id == project_id)
        )
        if row:
            row.bid_type     = bid_type
            row.price_method = price_method
            await session.commit()


async def load_participants_to_db(excel_path: Path, project_id: str) -> tuple[int, str]:
    """참여자 Excel -> DB 적재. (삽입한 참여자 행 수, 저장에 쓴 project_id) 반환.

    파싱은 `app.etl.participant_excel`, 쓰기는 `app.db.crud_collect` 가 한다 (T-035).
    한 장에서 참여자 행(업체 식별자 포함) 외에 추정가격과 복수예가 15개도 같이 꺼낸다.

    투찰율은 **원본 컬럼을 그대로 믿지 않고 투찰금액에서 다시 계산한다.**
    원본은 보통 A값이 반영된 조정값을 주지만 공고에 따라 그렇지 않다 —
    A값 공고 14,579개 중 1,158개(7.9%)에서 전 참여자 행이 어긋난다.
    예정가격을 모르면 재계산할 수 없으므로 그때만 원본값을 쓴다.
    목록 leg 가 먼저 돌면(daily_collect) 예정가격은 이미 들어와 있다.
    """
    from app.db.session import AsyncSessionLocal
    from app.db.crud_collect import save_participant_workbook
    from app.etl.participant_excel import parse_participant_workbook

    try:
        wb = parse_participant_workbook(excel_path)
    except Exception as e:
        print(f"    [!] Excel 읽기 실패: {e}")
        return 0, project_id
    if not wb.rows:
        print(f"    [!] 참여자 행을 찾을 수 없음")
        return 0, project_id

    # 상세 페이지의 공고번호에는 연도가 없다. Excel 헤더의 개찰일시로 정규화한다 (T-037).
    from app.etl.project_id import canonical_project_id
    pid = canonical_project_id(project_id, wb.open_at)
    async with AsyncSessionLocal() as session:
        res = await save_participant_workbook(session, wb, project_id=pid)
    return res.participants_inserted, pid


# ── 메인 ──────────────────────────────────────────────────────────────────────

async def run(
    start_date: str, end_date: str, license_type: str,
    user_id: str, password: str, headless: bool,
) -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    done = load_done()
    print(f"이미 완료: {len(done)}건")

    BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

    async with async_playwright() as pw:
        launch_kwargs: dict = {"headless": headless}
        if Path(BRAVE_PATH).exists():
            launch_kwargs["executable_path"] = BRAVE_PATH
        browser = await pw.chromium.launch(**launch_kwargs)
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        await login(page, user_id, password)

        links = await search_and_collect_links(page, start_date, end_date, license_type)
        if not links:
            print("수집할 공고 없음.")
            await browser.close()
            return

        total_ok = total_skip = total_err = 0

        async def ensure_page():
            """브라우저/페이지가 죽었으면 재시작해서 새 page 반환."""
            nonlocal browser, context, page
            try:
                await page.title()  # 살아있는지 확인
                return page
            except Exception:
                print("  [브라우저 재시작]")
                try:
                    await browser.close()
                except Exception:
                    pass
                browser = await pw.chromium.launch(**launch_kwargs)
                context = await browser.new_context(accept_downloads=True)
                page    = await context.new_page()
                await login(page, user_id, password)
                return page

        for idx, (bidid, url) in enumerate(links, 1):
            if bidid in done:
                total_skip += 1
                continue

            print(f"\n[{idx}/{len(links)}] {bidid}")

            try:
                page = await ensure_page()

                # 1. 상세 페이지 파싱
                info = await parse_detail(page, url)

                if info is None or info.get("skip"):
                    reason = info.get("reason", "") if info else "파싱실패"
                    print(f"  -> 스킵: {reason}")
                    log_result(bidid, "SKIP", reason)
                    total_skip += 1
                    continue

                print(f"  bid_type={info['bid_type']}, price_method={info['price_method']}")

                g2b_id = info.get("g2b_notice_id")

                # 2. 참여자 Excel 다운로드
                excel_path = await download_excel(page, context, bidid)
                if not excel_path:
                    log_result(bidid, "ERR", "Excel 다운 실패")
                    total_err += 1
                    continue

                # 3. DB 적재 + bids_history 갱신. 국방부형 번호는 개찰 연도가 붙어야
                #    맞는 공고를 가리키므로 Excel 을 읽은 뒤에 갱신한다 (T-037).
                if g2b_id:
                    n, pid = await load_participants_to_db(excel_path, g2b_id)
                    print(f"  -> 참여자 {n}건 적재 ({pid})")
                    await update_bid_type_and_method(pid, info["bid_type"], info["price_method"])

                log_result(bidid, "OK", f"{info['bid_type']} / {info['price_method']}")
                done.add(bidid)
                total_ok += 1

            except Exception as e:
                err_msg = str(e)[:100]
                print(f"  [!] 오류: {err_msg}")
                log_result(bidid, "ERR", err_msg)
                total_err += 1

            try:
                await page.wait_for_timeout(300)
            except Exception:
                pass

        try:
            await browser.close()
        except Exception:
            pass

    print(f"\n=== 완료: {total_ok}건 성공 / {total_skip}건 스킵 / {total_err}건 오류 ===")


def main():
    parser = argparse.ArgumentParser(description="Info21c 참여자 데이터 수집")
    parser.add_argument("--start",    required=True, help="시작일 YYYYMMDD")
    parser.add_argument("--end",      required=True, help="종료일 YYYYMMDD")
    parser.add_argument("--type",     choices=["0002", "0023"], required=True,
                        help="공종: 0002=실내건축, 0023=조경")
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
