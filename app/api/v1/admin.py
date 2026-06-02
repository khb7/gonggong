"""
app/api/v1/admin.py
CSV 파일 업로드 / 텍스트 붙여넣기로 bids_history 에 데이터를 추가하는 관리자 API.

지원 포맷:
  1. 단순 포맷 (simple): 컬럼 직접 입력
     공고번호,발주처,지역,공종,기초금액,낙찰하한율,사정률,낙찰가,참여업체수,개찰일자
  2. 나라장터 원본 (g2b): 기존 etl_csv.py 와 동일한 로직

POST /api/v1/admin/import-csv
  - form field `format`: "simple" | "g2b"
  - form field `file`: CSV 파일 (선택)
  - form field `text`: CSV 텍스트 붙여넣기 (선택, simple 포맷만 지원)
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models import BidsHistory, BidLicenseType, BidParticipants
from app.db.normalize import (
    normalize_project_type,
    parse_license_types,
    normalize_region,
    normalize_bid_type,
    normalize_price_method,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

router = APIRouter()


# ---------------------------------------------------------------------------
# HTML 관리 페이지
# ---------------------------------------------------------------------------

_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>데이터 가져오기 — 공공입찰 엔진</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', sans-serif; background: #f4f6f9; color: #333; padding: 32px; }
  h1 { font-size: 1.4rem; margin-bottom: 24px; color: #1a1a2e; }
  .card { background: #fff; border-radius: 10px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.08); max-width: 820px; }
  h2 { font-size: 1rem; margin-bottom: 12px; color: #555; }
  label { display: block; font-size: .85rem; margin-bottom: 4px; color: #666; }
  select, input[type=file], textarea {
    width: 100%; padding: 8px 10px; border: 1px solid #ddd; border-radius: 6px;
    font-size: .9rem; margin-bottom: 16px;
  }
  textarea { font-family: monospace; height: 220px; resize: vertical; }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab { padding: 6px 18px; border: 1px solid #ccc; border-radius: 20px; cursor: pointer;
         font-size: .85rem; background: #fff; }
  .tab.active { background: #3b5bdb; color: #fff; border-color: #3b5bdb; }
  .panel { display: none; }
  .panel.active { display: block; }
  button[type=submit] {
    background: #3b5bdb; color: #fff; border: none; border-radius: 6px;
    padding: 10px 28px; font-size: .95rem; cursor: pointer;
  }
  button[type=submit]:hover { background: #2f4ac4; }
  #result { margin-top: 20px; padding: 14px; border-radius: 8px; display: none; font-size: .9rem; }
  .success { background: #d3f9d8; color: #2b8a3e; border: 1px solid #69db7c; }
  .error   { background: #ffe3e3; color: #c92a2a; border: 1px solid #ffa8a8; }
  .hint { font-size: .78rem; color: #888; margin-top: -12px; margin-bottom: 14px; }
  pre.schema { background: #f8f9fa; border: 1px solid #e9ecef; border-radius: 6px;
               padding: 12px; font-size: .78rem; overflow-x: auto; margin-bottom: 16px; }
  .spinner { display: none; margin-left: 10px; }
</style>
</head>
<body>
<h1>📥 입찰 데이터 가져오기</h1>
<div class="card">
  <h2>포맷 선택</h2>
  <select id="fmt" onchange="onFmtChange()">
    <option value="simple">단순 포맷 (직접 작성 / 붙여넣기)</option>
    <option value="g2b">나라장터 원본 CSV (2개 파일)</option>
  </select>

  <!-- 단순 포맷 안내 -->
  <div id="schemaBox">
    <p style="font-size:.8rem;color:#666;margin-bottom:8px">▸ 낙찰자(1순위)만 있는 경우</p>
    <pre class="schema">공고번호,발주처,발주청코드,지역,공종,입찰방식,기초금액,낙찰하한율,사정률,낙찰가,참여업체수,개찰일자,예정가격방식
20240101001,서울특별시,6110000,서울,실내건축,적격심사,50000000,0.87745,0.9910,49500000,15,2024-01-15,복수예비가격</pre>
    <p style="font-size:.8rem;color:#666;margin-bottom:8px;margin-top:12px">▸ 전체 순위 포함 (개찰순위·투찰금액·투찰율 컬럼 추가 — 참여자 분석용)</p>
    <pre class="schema">공고번호,발주처,지역,공종,입찰방식,기초금액,낙찰하한율,사정률,낙찰가,참여업체수,개찰일자,개찰순위,투찰금액,투찰율
20240101001,서울특별시,서울,실내건축,적격심사,50000000,0.87745,0.9910,49500000,15,2024-01-15,1,49500000,0.9950
20240101001,서울특별시,서울,실내건축,적격심사,50000000,0.87745,0.9910,49500000,15,2024-01-15,2,49480000,0.9948
20240101001,서울특별시,서울,실내건축,적격심사,50000000,0.87745,0.9910,49500000,15,2024-01-15,3,49520000,0.9952</pre>
    <p class="hint">
      • 개찰순위 컬럼이 있으면 전체 순위를 bid_participants에도 저장 (경쟁 분포 분석용)<br>
      • 낙찰하한율·사정률·투찰율: 소수(0.877) 또는 퍼센트(87.7) 모두 허용<br>
      • 입찰방식: 적격심사 / 최저가 / 협상 &nbsp;|&nbsp; 예정가격방식: 복수예비가격 / 고정예정가격
    </p>
  </div>

  <!-- 입력 탭 (단순 포맷) -->
  <div id="simpleTabs">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('paste')">텍스트 붙여넣기</div>
      <div class="tab" onclick="switchTab('file')">파일 업로드</div>
    </div>
    <div id="pastePanel" class="panel active">
      <label>CSV 내용 붙여넣기 (첫 행은 헤더)</label>
      <textarea id="csvText" placeholder="공고번호,발주처,지역,공종,...&#10;20240101001,..."></textarea>
    </div>
    <div id="filePanel" class="panel">
      <label>CSV 파일 선택</label>
      <input type="file" id="csvFile" accept=".csv,.tsv,.txt">
    </div>
  </div>

  <!-- 나라장터 원본 (g2b) -->
  <div id="g2bSection" style="display:none">
    <label>입찰공고 내역 CSV (UI-ADODAA-008R)</label>
    <input type="file" id="g2bNotice" accept=".csv,.tsv,.txt">
    <label>입찰공고 결과내역 CSV (UI-ADOFAA-003R)</label>
    <input type="file" id="g2bResult" accept=".csv,.tsv,.txt">
  </div>

  <button type="submit" onclick="doImport()">가져오기 시작</button>
  <span class="spinner" id="spinner">⏳ 처리 중...</span>
  <div id="result"></div>
</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById(name + 'Panel').classList.add('active');
}

function onFmtChange() {
  const g2b = document.getElementById('fmt').value === 'g2b';
  document.getElementById('simpleTabs').style.display = g2b ? 'none' : '';
  document.getElementById('schemaBox').style.display = g2b ? 'none' : '';
  document.getElementById('g2bSection').style.display = g2b ? '' : 'none';
}

async function doImport() {
  const fmt = document.getElementById('fmt').value;
  const spinner = document.getElementById('spinner');
  const resultEl = document.getElementById('result');
  resultEl.style.display = 'none';
  spinner.style.display = 'inline';

  const fd = new FormData();
  fd.append('format', fmt);

  if (fmt === 'simple') {
    const activeTab = document.querySelector('.tab.active').textContent.trim();
    if (activeTab === '텍스트 붙여넣기') {
      const txt = document.getElementById('csvText').value.trim();
      if (!txt) { showResult('error', 'CSV 내용을 입력해 주세요.'); spinner.style.display='none'; return; }
      fd.append('text', txt);
    } else {
      const f = document.getElementById('csvFile').files[0];
      if (!f) { showResult('error', '파일을 선택해 주세요.'); spinner.style.display='none'; return; }
      fd.append('file', f);
    }
  } else {
    const fn = document.getElementById('g2bNotice').files[0];
    const fr = document.getElementById('g2bResult').files[0];
    if (!fn || !fr) { showResult('error', '공고 내역과 결과 내역 파일을 모두 선택해 주세요.'); spinner.style.display='none'; return; }
    fd.append('file_notice', fn);
    fd.append('file_result', fr);
  }

  try {
    const resp = await fetch('/api/v1/admin/import-csv', { method: 'POST', body: fd });
    const data = await resp.json();
    if (resp.ok) {
      showResult('success',
        `✅ 완료 — 낙찰 데이터: ${data.bids_inserted}건 추가 / ${data.bids_skipped}건 중복 스킵 ` +
        `| 참여자 데이터: ${data.participants_inserted}건 추가 / ${data.participants_skipped}건 중복 스킵`
      );
    } else {
      showResult('error', '❌ 오류: ' + (data.detail || JSON.stringify(data)));
    }
  } catch (e) {
    showResult('error', '❌ 네트워크 오류: ' + e.message);
  }
  spinner.style.display = 'none';
}

function showResult(type, msg) {
  const el = document.getElementById('result');
  el.className = type;
  el.textContent = msg;
  el.style.display = 'block';
}
</script>
</body>
</html>
"""


@router.get("/admin/import", response_class=HTMLResponse, include_in_schema=False)
async def import_page():
    return _HTML


# ---------------------------------------------------------------------------
# 단순 포맷 파서
# ---------------------------------------------------------------------------

def _parse_rate(val) -> Decimal | None:
    """퍼센트(87.7) 또는 소수(0.877) 모두 소수로 반환."""
    try:
        d = Decimal(str(val).strip())
        if d > 1:
            d = d / 100
        return d
    except InvalidOperation:
        return None


def _parse_simple(content: str) -> tuple[list[dict], list[dict]]:
    """
    단순 포맷 CSV 파싱.

    Returns:
        (bids_records, participants_records)
        - bids_records: bids_history 삽입용 (rank=1 행 또는 rank 컬럼 없는 경우 전체)
        - participants_records: bid_participants 삽입용 (rank 컬럼 있을 때만)
    """
    df = pd.read_csv(io.StringIO(content), dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]

    alias = {
        "공고번호": "project_id",
        "발주처": "client_name",
        "발주청코드": "client_id",
        "지역": "region",
        "공종": "_raw_project_type",
        "입찰방식": "bid_type",
        "기초금액": "base_price",
        "낙찰하한율": "lower_limit_rate",
        "사정률": "adjustment_rate",
        "낙찰가": "winner_price",
        "참여업체수": "participants",
        "개찰일자": "bid_date",
        "예정가격방식": "price_method",
        "개찰순위": "rank",
        "투찰금액": "bid_amount",
        "투찰율": "bid_rate",
    }
    df.rename(columns=alias, inplace=True)

    has_rank = "rank" in df.columns
    missing = {"project_id", "region", "_raw_project_type",
               "base_price", "lower_limit_rate", "adjustment_rate", "participants"} - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼 누락: {missing}")

    bids_records: list[dict] = []
    participants_records: list[dict] = []
    errors: list[str] = []

    # rank 컬럼이 있으면 공고별로 rank=1 행에서 bids_history 정보를 읽는다
    # rank 컬럼이 없으면 모든 행을 rank=1(낙찰자)로 간주
    for i, row in df.iterrows():
        line = i + 2
        rank = int(str(row.get("rank", "1")).strip()) if has_rank else 1

        try:
            base_price_str = str(row["base_price"]).replace(",", "").strip()
            base_price = int(float(base_price_str))
            if base_price <= 0:
                errors.append(f"행 {line}: 기초금액 0 이하")
                continue

            # participants_records: rank 컬럼이 있으면 모든 행 저장
            if has_rank:
                bid_amount_raw = str(row.get("bid_amount", "")).replace(",", "").strip()
                bid_rate_raw = _parse_rate(str(row.get("bid_rate", "")).strip())
                if bid_amount_raw and bid_rate_raw is not None:
                    participants_records.append({
                        "project_id": str(row["project_id"]).strip(),
                        "rank": rank,
                        "bid_amount": int(float(bid_amount_raw)),
                        "bid_rate": bid_rate_raw,
                        "is_winner": rank == 1,
                    })

            # bids_records: rank=1 행만
            if rank != 1:
                continue

            lower = _parse_rate(row["lower_limit_rate"])
            adj = _parse_rate(row["adjustment_rate"])
            if lower is None or adj is None:
                errors.append(f"행 {line}: 비율 파싱 실패")
                continue

            participants_str = str(row["participants"]).replace(",", "").strip()
            participants = int(float(participants_str))

            winner_raw = str(row.get("winner_price", "")).replace(",", "").strip()
            winner_price = int(float(winner_raw)) if winner_raw else None

            date_raw = str(row.get("bid_date", "")).strip()
            bid_date: date | None = None
            if date_raw:
                try:
                    bid_date = pd.to_datetime(date_raw).date()
                except Exception:
                    pass

            raw_type = str(row.get("_raw_project_type", "")).strip()
            # 단순 포맷: 공종 컬럼은 "실내건축" 같은 단일값 → 정규화 후 단일 license type 생성
            normalized = normalize_project_type(raw_type)
            license_types = ([{"type_name": normalized, "size": None, "is_mutual": False, "is_primary": True}]
                             if normalized else [])
            if not license_types:
                errors.append(f"행 {line}: 알 수 없는 공종 '{raw_type}'")
                continue

            client_raw = str(row.get("client_name", "")).strip()
            client_id_raw = str(row.get("client_id", "")).strip()

            bids_records.append({
                "project_id": str(row["project_id"]).strip(),
                "client_name": client_raw if client_raw else None,
                "client_id": client_id_raw if client_id_raw else None,
                "region": normalize_region(str(row["region"]).strip()),
                "_license_types": license_types,
                "bid_type": normalize_bid_type(str(row.get("bid_type", "")).strip()),
                "price_method": normalize_price_method(str(row.get("price_method", "")).strip()),
                "base_price": base_price,
                "lower_limit_rate": lower,
                "adjustment_rate": adj,
                "winner_price": winner_price,
                "participants": participants,
                "bid_date": bid_date,
            })
        except Exception as e:
            errors.append(f"행 {line}: {e}")

    if errors:
        raise ValueError("파싱 오류:\n" + "\n".join(errors[:10]))

    return bids_records, participants_records


# ---------------------------------------------------------------------------
# 나라장터 원본 포맷 파서
# ---------------------------------------------------------------------------

def _parse_license_types_g2b(val: str) -> list[dict]:
    """나라장터 면허업종제한목록 원문 → BidLicenseType 레코드 리스트."""
    if not val or val == "nan":
        return []
    return parse_license_types(val)


def _parse_g2b(notice_bytes: bytes, result_bytes: bytes) -> tuple[list[dict], list[dict]]:
    """
    나라장터 원본 CSV 파싱.

    Returns:
        (bids_records, participants_records)
        - bids_records: rank=1 행만 → bids_history
        - participants_records: 전체 순위 → bid_participants
    """
    def _read(b: bytes, skiprows) -> pd.DataFrame:
        for enc in ("utf-16", "utf-8-sig", "euc-kr"):
            try:
                return pd.read_csv(
                    io.BytesIO(b), sep="\t", encoding=enc,
                    skiprows=skiprows, dtype=str, keep_default_na=False
                )
            except Exception:
                continue
        raise ValueError("파일 인코딩을 인식할 수 없습니다 (utf-16 / utf-8 / euc-kr 지원)")

    df_notice = _read(notice_bytes, list(range(106)) + list(range(107, 125)))
    df_result = _read(result_bytes, 74)

    df_notice.columns = df_notice.columns.str.strip()
    df_result.columns = df_result.columns.str.strip()

    # 순위 필터 제거 — 전체 순위를 participants에 저장
    df = pd.merge(df_result, df_notice, on="입찰공고번호", how="inner", suffixes=("", "_notice"))

    bids_records: list[dict] = []
    participants_records: list[dict] = []

    for _, row in df.iterrows():
        try:
            rank_raw = str(row.get("개찰순위", "1")).strip()
            rank = int(rank_raw) if rank_raw.isdigit() else 1

            bid_amount_raw = str(row.get("투찰금액", "0")).replace(",", "")
            bid_amount = int(float(bid_amount_raw)) if bid_amount_raw else 0

            bid_rate_raw = str(row.get("투찰율", "")).strip()
            bid_rate = _parse_rate(bid_rate_raw)

            project_id = str(row["입찰공고번호"]).strip()

            # bid_participants: 투찰금액과 투찰율이 있는 모든 행
            if bid_amount > 0 and bid_rate is not None:
                participants_records.append({
                    "project_id": project_id,
                    "rank": rank,
                    "bid_amount": bid_amount,
                    "bid_rate": bid_rate,
                    "is_winner": rank == 1,
                })

            # bids_history: rank=1 행만
            if rank != 1:
                continue

            base_price = float(str(row.get("기초금액", 0)).replace(",", ""))
            est_price = float(str(row.get("예정가격", 0)).replace(",", ""))
            lower = float(row.get("낙찰하한율", 0))
            participants = int(row.get("입찰참여자수", 0))

            if base_price <= 0 or est_price <= 0 or participants <= 0:
                continue
            adj = est_price / base_price
            if not (0.95 < adj < 1.05):
                continue

            license_types = _parse_license_types_g2b(str(row.get("면허업종제한목록", "")))
            if not license_types:
                continue

            if lower > 1:
                lower /= 100.0

            raw_bid_type = str(row.get("낙찰방법", row.get("입찰방법", ""))).strip()
            raw_price_method = str(row.get("예정가격결정방법", row.get("예정가격방법", ""))).strip()

            bids_records.append({
                "project_id": project_id,
                "client_name": str(row.get("수요기관명", "")).strip() or None,
                "client_id": str(row.get("수요기관코드", "")).strip() or None,
                "region": normalize_region(str(row.get("현장지역", "")).strip()),
                "_license_types": license_types,
                "bid_type": normalize_bid_type(raw_bid_type),
                "price_method": normalize_price_method(raw_price_method),
                "base_price": int(base_price),
                "lower_limit_rate": Decimal(str(lower)),
                "adjustment_rate": Decimal(str(round(adj, 6))),
                "winner_price": bid_amount if bid_amount > 0 else None,
                "participants": participants,
                "bid_date": None,
            })
        except Exception:
            continue

    return bids_records, participants_records


# ---------------------------------------------------------------------------
# DB 저장
# ---------------------------------------------------------------------------

async def _bulk_insert(
    bids: list[dict],
    participants: list[dict],
) -> dict:
    """bids_history + bid_participants 동시 삽입. 중복은 모두 스킵."""
    async with AsyncSessionLocal() as session:
        b_inserted = b_skipped = 0
        if bids:
            # _license_types 키 분리 후 bids_history 삽입
            license_map: dict[str, list[dict]] = {}
            bids_only = []
            for rec in bids:
                rec = dict(rec)
                license_map[rec["project_id"]] = rec.pop("_license_types", [])
                bids_only.append(rec)

            stmt = pg_insert(BidsHistory).values(bids_only)
            stmt = stmt.on_conflict_do_nothing(index_elements=["project_id"])
            res = await session.execute(stmt)
            b_inserted = res.rowcount
            b_skipped = len(bids) - b_inserted

            # bid_license_types 삽입
            lt_values = [
                {"project_id": pid, **lt}
                for pid, lts in license_map.items()
                for lt in lts
            ]
            if lt_values:
                lt_stmt = pg_insert(BidLicenseType).values(lt_values)
                lt_stmt = lt_stmt.on_conflict_do_nothing(index_elements=["project_id", "type_name"])
                await session.execute(lt_stmt)

        p_inserted = p_skipped = 0
        if participants:
            stmt = pg_insert(BidParticipants).values(participants)
            stmt = stmt.on_conflict_do_nothing(
                constraint="uq_bid_participants_project_rank"
            )
            res = await session.execute(stmt)
            p_inserted = res.rowcount
            p_skipped = len(participants) - p_inserted

        await session.commit()

    return {
        "bids_inserted": b_inserted,
        "bids_skipped": b_skipped,
        "participants_inserted": p_inserted,
        "participants_skipped": p_skipped,
    }


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@router.post("/admin/import-csv")
async def import_csv(
    format: str = Form(...),
    text: str = Form(None),
    file: UploadFile = File(None),
    file_notice: UploadFile = File(None),
    file_result: UploadFile = File(None),
):
    """
    CSV 데이터를 bids_history + bid_participants 에 삽입한다.

    - **format=simple**: 단순 컬럼 포맷 (텍스트 붙여넣기 or 파일)
    - **format=g2b**: 나라장터 원본 CSV 2개 파일
    """
    try:
        if format == "simple":
            if text:
                content = text
            elif file:
                raw = await file.read()
                for enc in ("utf-8-sig", "utf-8", "euc-kr", "utf-16"):
                    try:
                        content = raw.decode(enc)
                        break
                    except Exception:
                        continue
                else:
                    raise HTTPException(status_code=400, detail="파일 인코딩 인식 실패")
            else:
                raise HTTPException(status_code=400, detail="text 또는 file 중 하나는 필수입니다.")

            bids, participants = _parse_simple(content)

        elif format == "g2b":
            if not file_notice or not file_result:
                raise HTTPException(status_code=400, detail="file_notice, file_result 모두 필요합니다.")
            notice_bytes = await file_notice.read()
            result_bytes = await file_result.read()
            bids, participants = _parse_g2b(notice_bytes, result_bytes)

        else:
            raise HTTPException(status_code=400, detail=f"알 수 없는 포맷: {format}")

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not bids and not participants:
        return JSONResponse({"message": "처리할 데이터가 없습니다.", "bids_inserted": 0, "participants_inserted": 0})

    result = await _bulk_insert(bids, participants)
    result["message"] = (
        f"낙찰 데이터 {result['bids_inserted']}건 추가 "
        f"/ 참여자 데이터 {result['participants_inserted']}건 추가"
    )
    return result
