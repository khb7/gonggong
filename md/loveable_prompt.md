# Loveable 프롬프트

아래 텍스트를 Loveable에 그대로 붙여넣으세요.

---

## 프롬프트 원문

```
Build a Korean public procurement bid price calculator dashboard web app called "공공입찰 투찰 계산기".

The app connects to a local FastAPI backend at http://localhost:8000.

---

## Pages & Navigation

Sidebar navigation with 5 pages:

1. 투찰가 계산 (Bid Calculator) — default page
2. 데이터 현황 (Data Overview)
3. 발주처 통계 (Client Statistics)
4. 사정률 분포 (Rate Distribution)
5. 데이터 수집 (Data Collection / Backfill)

---

## Page 1: 투찰가 계산 (Bid Calculator)

Main input section:
- Large text input: "공고번호" (placeholder: "예: R25BK00678040")
- "계산하기" primary button

Collapsible section "수동 입력 (Override)" — collapsed by default:
- Number input: "기초금액 (원)" (placeholder: "예: 500000000")
- Number input: "낙찰하한율" (placeholder: "예: 0.87745")
- Number input: "참여 업체 수" (placeholder: "예: 150")
- Small note: "입력한 항목이 API 조회값을 대체합니다"

After calculation, show results section:

Info bar (gray background):
- 발주처: [client_name]
- 지역: [region]
- 공종: [project_type]
- 기초금액: [base_price formatted with comma, 원]
- 하한율: [lower_limit_rate * 100, 2 decimal places, %]
- 참여업체: [participants]명
- 예측 사정률: [predicted_rate * 100, 4 decimal places, %]
- 신뢰도: badge showing fallback_level
  - "발주처 이력" (client) → green badge
  - "지역 이력" (region) → blue badge
  - "공종+금액" (type_bucket) → yellow badge
  - "전체 평균" (global) → orange badge
  - "데이터 없음" (none or default) → red badge
- 전략: [strategy] — "안전" (safe) / "보통" (normal) / "공격적" (aggressive)

3 result cards side by side:
Card labels: "공격적" (Aggressive) / "보통" (Normal) / "안전" (Safe)
Each card shows:
- Large: price_krw formatted with comma + "원"
- Medium: rate_pct + "%"
- Small gray: "digit filter 적용됨" if digit_filter_applied is true
Highlight the card matching the strategy field.

API call:
POST http://localhost:8000/api/v1/bid/calculate
Body: { "bid_notice_id": "...", "overrides": { "base_price": null, "lower_limit_rate": null, "participants": null } }
Remove null fields from overrides before sending. If all overrides are null, send without overrides field.

Response type:
{
  "bid_notice_id": "string",
  "mode": "auto" | "override",
  "overridden_fields": ["string"],
  "g2b_fetch_status": "ok" | "failed" | "mock",
  "fetched": {
    "base_price": 500000000,
    "client_name": "서울시",
    "region": "서울",
    "project_type": "건축공사업",
    "lower_limit_rate": 0.87745,
    "participants": 120
  },
  "strategy": "normal",
  "predicted_rate": 0.9234,
  "mad_value": 0.0031,
  "fallback_level": "client",
  "bids": [
    { "label": "Aggressive", "rate_pct": 87.645, "price_krw": 438225000, "digit_filter_applied": false },
    { "label": "Normal",     "rate_pct": 87.745, "price_krw": 438725000, "digit_filter_applied": false },
    { "label": "Safe",       "rate_pct": 87.845, "price_krw": 439225000, "digit_filter_applied": true }
  ]
}

---

## Page 2: 데이터 현황 (Data Overview)

Call GET http://localhost:8000/api/v1/stats/overview on mount.

Response type:
{
  "total_records": 120000,
  "date_range": { "start": "2025-01-08", "end": "2026-03-16" },
  "last_collected": "2026-03-16",
  "by_project_type": {
    "건축공사업": 95000,
    "조경식재공사업": 25000
  }
}

Layout:
- Top row: 4 stat cards
  - 총 수집 건수 (total_records, formatted with comma)
  - 수집 시작일 (date_range.start)
  - 최근 수집일 (last_collected)
  - 수집 기간 (days between date_range.start and date_range.end, "N일")

- Middle row: bar chart showing by_project_type (건수)

---

## Page 3: 발주처 통계 (Client Statistics)

Call GET http://localhost:8000/api/v1/stats/clients on mount.

Response type:
[
  {
    "client_name": "서울시",
    "record_count": 1500,
    "avg_adjustment_rate": 0.9123,
    "avg_participants": 145.3
  }
]
Sorted by record_count descending.

Layout:
- Horizontal bar chart: top 20 발주처 by record_count
- Below: sortable table with all columns
  - 발주처명 | 낙찰 건수 | 평균 사정률 (%) | 평균 참여업체

---

## Page 4: 사정률 분포 (Rate Distribution)

Call GET http://localhost:8000/api/v1/stats/distribution on mount.
Supports query param: ?project_type=건축공사업 (optional)

Response type:
{
  "bins": [0.855, 0.865, 0.875, 0.885, 0.895, 0.905, 0.915, 0.925],
  "counts": [120, 340, 890, 1450, 2100, 1800, 1200, 600],
  "total": 8500,
  "median": 0.8923,
  "mad": 0.0031,
  "min_rate": 0.851,
  "max_rate": 0.932
}

Layout:
- Filter buttons at top: 전체 / 건축공사업 / 조경식재공사업
- Bar chart (histogram): x-axis = 사정률 (%), y-axis = 건수
- Vertical reference line at median value
- Below chart: stat cards for 중앙값 (%), MAD, 총 건수

---

## Page 5: 데이터 수집 (Data Collection)

Two sections:

### Section 1: 백필 현황 (Backfill Status)
Call GET http://localhost:8000/api/v1/stats/backfill on mount and poll every 3 seconds when is_running is true.

Response type:
{
  "is_running": false,
  "progress": {
    "chunk_current": 25,
    "chunk_total": 63,
    "chunk_start": "2025-06-01",
    "chunk_end": "2025-06-07",
    "records_so_far": 1842
  },
  "last_run": {
    "started_at": "2026-03-17T09:00:00",
    "completed_at": "2026-03-17T09:45:00",
    "start_date": "2025-01-01",
    "end_date": "2026-03-16",
    "inserted": 12345,
    "error": null
  }
}

When is_running is true:
- Show progress bar: chunk_current / chunk_total
- Show current chunk: "수집 중: YYYY-MM-DD ~ YYYY-MM-DD"
- Show records so far: "누적 N건"
- Show spinner

When is_running is false and last_run exists:
- Show last run summary card:
  - 실행 시간: started_at ~ completed_at
  - 기간: start_date ~ end_date
  - 신규 등록: inserted건
  - If error is not null, show red error message

### Section 2: 백필 실행 (Trigger Backfill)
- Date range picker: 시작일 / 종료일 (default: last 90 days)
- "백필 시작" button
- On click: POST http://localhost:8000/api/v1/stats/backfill
  Body: { "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD" }
- If 409 response: show toast "이미 실행 중입니다"
- If 400 response: show toast with error detail
- On success: show toast "백필을 시작합니다" and start polling

---

## Design

- Korean language UI throughout
- Dark sidebar, light content area
- Primary color: blue (#2563eb)
- Numbers formatted with Korean locale (천 단위 comma)
- Loading spinner during API calls
- Error toast when API fails: "서버 연결 실패. 백엔드가 실행 중인지 확인하세요."
- Responsive but desktop-first (min-width 1024px)
```
