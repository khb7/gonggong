<<<<<<< HEAD
# Handoff — T-031 투찰가 계산기 요약에서 고정 사정률 내리기 — 2026-09-10

## 변경한 파일

- `app/api/v1/bidding.py` — 사정률 산포를 전역 상수에서 계약법별 값으로 교체.
  `PREPRICE_MAD` 모듈 상수 제거, `contract_law.preprice_mad(client_name)` 사용.
  응답에 `contract_law`, `base_price`(계산에 실제로 쓴 값) 추가.
  `FIXED_PREPRICE_RATE` 주석에 "옮기지 말 것" 근거(전체 DB 스윕 평탄성) 추가.
- `app/schemas/response.py` — `BidResponse.contract_law` / `BidResponse.base_price` 신설.
- `frontend/src/lib/api.ts` — `BidResult` 에 두 필드 추가. `prediction_range` 는
  중심이 고정 사정률이라 표시용으로 쓰지 않는다고 주석에 명시.
- `frontend/src/pages/BidCalculator.tsx` — 요약 카드 교체 + `LAW_LABEL` 추가.
- `tests/test_api_bidding.py` — 신규 2개 (계약법별 산포 / unknown 폴백).
- `frontend/src/pages/BidCalculator.test.tsx` — 6개로 재작성.

## Eval 에이전트가 확인해야 할 포인트

**화면:** `/calculator` — 공고번호 + 기초금액 + 낙찰하한율 입력 후 계산.

1. 요약 카드 첫 줄이 **「예정가격 추정: N원 ~ N원」** 이다.
   "적용 사정률: 100.15%" 는 **없어야 한다.**
2. 둘째 항목이 「사정률 산포: ±0.52%p  지방계약 ±3%」 형태.
3. **발주처를 바꾸면 세 값이 같이 바뀐다.** 이게 이번 변경의 핵심이다.

   | 발주처 입력 | 라벨 | 산포 | 예정가격 범위 (기초 10억) |
   |---|---|---|---|
   | 서울특별시 | 지방계약 ±3% | ±0.52%p | 994,809,000 ~ 1,005,191,000 |
   | 국군재정관리단 | 국가계약 ±2% | ±0.38%p | 996,226,000 ~ 1,003,774,000 |
   | 조달청 인천지방조달청 | 지방조달청 대행 | ±0.47%p | 995,231,000 ~ 1,004,769,000 |
   | (빈칸/불명) | 구분 불명 | ±0.49%p | 995,144,000 ~ 1,004,856,000 |

4. 범위 중심이 **기초금액 그대로**여야 한다 (10억이면 10억이 정중앙).
   100.15% 를 중심으로 잡혀 위로 밀려 있으면 회귀다.
5. 각주에 고정 기준 `100.15%` 가 계산 근거로 남아 있다. 투찰가 카드의
   산식줄 `(기초금액 × 100.15% − A값) × 하한율 + A값` 도 그대로.

**API:** `POST /api/v1/bid/distribution` 아님 — `POST /api/v1/bid/calculate` 다.
```
curl -s localhost:8000/api/v1/bid/calculate -H 'content-type: application/json'   -d '{"bid_notice_id":"X","overrides":{"base_price":1000000000,
       "lower_limit_rate":0.89745,"client_name":"국군재정관리단"}}' | jq '.contract_law,.mad_value,.base_price'
```
→ `"national"` / `0.003774` / `1000000000`

## 알려진 미해결 사항

- `/bid/calculate` 는 여전히 동결 경로다. 이번 변경은 표시 정합성 수정이지
  기능 추가가 아니다. 신규 기능은 계속 분포 경로에 붙인다.
- `prediction_range` 필드는 응답에 남아 있지만 이제 아무도 안 쓴다.
  중심이 고정 사정률이라 의미가 애매하다 — 다음에 정리 대상.
- 자동 수집이 멈춰 있다. `max(bid_date) = 2026-08-28` 로 이 시점 13일 공백.
  Windows 작업 스케줄러에 `daily_collect.py` 가 등록돼 있지 않다 (docs/deployment.md 9절).
=======
# Handoff — 내 위치 사정률 오차 밴드 (T-014) — 2026-09-01

## 배경

분포 화면의 x축(과거 참여자 offset)은 `bid_participants.bid_rate`, 즉 개찰로 확정된
**예정가격** 기준값이다. 반면 내 투찰가는 개찰 전이라 예정가격을 모르므로
**기초금액**으로 대신 쟀다 (사정률≈1.0 근사).

자가 서로 다르므로 내 화살표는 사정률이 흔들리는 만큼 좌우로 밀린다.

```
예정가격 = 기초금액 × 사정률
내 offset = (투찰금액 − A) / (기초금액 × 사정률 − A) − 법정하한율
```

실측 σ = 0.007197 (bids_history 18,409건). 투찰율 0.9 기준 약 ±0.65%p = bin 6칸.
낙찰 집중 구간 폭보다 넓을 수 있는데 점 하나로 그려서 실제보다 정밀해 보였다.

오차 자체는 제거할 수 없다. **폭을 드러내는 것**이 이번 변경의 목적이다.

## 변경한 파일

### 백엔드
- `app/db/crud_distribution.py` — `get_adjustment_rate_sigma()` 추가.
  `stddev_samp(adjustment_rate)` 를 전체 표본에서 계산하고 캐시(TTL 30분)한다.
  표본 100건 미만이거나 σ > 0.05 면 `None` (밴드 안 그림).
  사정률 0.90~1.10 밖은 적재 오염으로 보고 제외.
- `app/engine/distribution.py` — `calc_offset_band()` 추가.
  밴드 하단 = 사정률 (1+σ), 상단 = (1−σ). `calc_my_position()` 에 `rate_sigma` 인자 추가.
- `app/schemas/distribution.py` — `MyPositionResponse` 에 `offset_low_pct` /
  `offset_high_pct` / `rate_sigma`, `DistributionResponse` 에 `rate_sigma` 추가. 전부 nullable.
- `app/api/v1/distribution.py` — σ 조회 후 `calc_my_position()` 에 전달.
  조회 실패 시 try/except 로 `None` 처리 — 분포 응답은 죽지 않고 밴드만 사라진다.

### 프론트
- `frontend/src/lib/api.ts` — `BidPosition` / `DistributionResult` 타입 확장
- `frontend/src/lib/distribution.ts` — `computeOffsetBand()` 추가,
  `computeLocalPosition()` 에 `rateSigma` 인자 + `offsetLowPct` / `offsetHighPct` 반환
- `frontend/src/pages/BidDistribution.tsx` —
  차트에 밴드 `ReferenceArea`(rose, 막대 뒤), 범례 항목, 하단 설명 문구,
  "내 offset" 카드에 범위 표시, 밴드 폭 ≥ 집중 구간 폭이면 경고 문구

### 테스트
- `tests/test_distribution.py` — 밴드 7건
- `tests/test_api_distribution.py` — 밴드 3건 (σ 없음 / 있음 / 조회 실패)
- `frontend/src/lib/distribution.test.ts` — 밴드 8건 (백엔드와 값 일치 검증 포함)

## Eval 에이전트가 확인해야 할 포인트

### API

`POST /api/v1/bid/distribution`

```json
{
  "bid_notice_id": "<실제 공고번호>",
  "overrides": {"base_price": 1000000000, "lower_limit_rate": 0.87745},
  "my_bid_price": 900000000
}
```

기대 응답:
- `rate_sigma` ≈ `0.0072` (실 DB 기준 0.007197)
- `my_position.offset_pct` = `2.3`
- `my_position.offset_low_pct` = `1.6`, `offset_high_pct` = `2.9`
- 항상 `offset_low_pct < offset_pct < offset_high_pct`

`my_bid_price` 없으면 `my_position` 은 null 이고 `rate_sigma` 만 채워진다.

### 화면 (`/distribution`)

투찰가를 입력하면:
1. 히스토그램에 빨간 점선 "내 위치" 선 **주변으로 연한 붉은 밴드**가 깔린다 (막대 뒤)
2. 범례에 "사정률 오차 범위 (±1σ)" 항목이 추가된다
3. 차트 아래 "내 위치는 점이 아니라 폭입니다 — 1.6% ~ 2.9%" 설명이 나온다
4. "내 offset" 카드에 큰 숫자 아래 작은 글씨로 범위가 붙는다
5. 밴드 폭이 낙찰 집중 구간 폭보다 넓으면 주황색 경고 문구가 뜬다
   — "이 구간을 정밀하게 겨냥할 수 있는 상황이 아닙니다"

밴드가 표시 범위 밖으로 나가면 `prepared.rangeFrom/rangeTo` 로 클램프된다.

## 알려진 미해결 사항

- **σ 를 발주기관 유형별로 나누지 않았다.** 제도상 예비가격 생성 구간이 다르지만
  (조달청 ±2% / 지자체 ±3%) 사정률은 그중 4개의 평균이라 차이가 흡수된다.
  실측 조달청 σ=0.0070 / 지자체 σ=0.0075 — σ 자체의 5% 수준이라 분기 실익이 없다.
  애초에 `BidsHistory` 에 기관 유형 필드가 없어서 나누려면 스키마부터 손봐야 한다.
- **`bid_preliminary_prices` 는 여전히 0행.** `scripts/collect_preliminary_prices.py` 가
  구현돼 있지만 실행된 적이 없다. 채우면 ±2/±3 규칙을 예비가격 원본으로 직접 검증할 수 있고,
  σ 를 사후 통계가 아니라 제도 파라미터에서 유도할 수 있다.
- **밴드는 ±1σ 고정.** 약 68% 구간이다. ±2σ 토글은 넣지 않았다.
- **`estimated_price`(기준 금액) 카드는 여전히 점 추정.** offset 밴드만 폭으로 바뀌었고
  금액은 사정률 1.0 가정값 하나만 보여준다.
- **`/bid/calculate`(동결 경로)는 손대지 않았다.** 밴드는 분포 경로에만 있다.
>>>>>>> origin/main
