# Distribution Engine 전환 분석 보고서

**작성일**: 2026-05-29  
**상태**: 참고용 (구현 전 분석)  
**배경**: 사정률 예측 엔진 폐기 후 경쟁자 분포 기반 의사결정 엔진으로 전환 시 모듈 영향 분석

---

## 1. 현재 `/bid/calculate` 흐름

```
POST /bid/calculate
│
├─ G2BFetcher.fetch()            → 기초금액, 하한율, 발주처, 지역, 공종
├─ Override 적용                 → 수동 입력값 덮어쓰기
├─ ProjectBucket.get_bucket_id() → 금액 구간 분류
│
├─ get_rates_with_fallback()     → bids_history.adjustment_rate 조회
│   ├─ get_rates_by_client()
│   ├─ get_rates_by_region()
│   ├─ get_rates_by_type_and_bucket()
│   └─ get_all_rates()           ← 최후 fallback
│
├─ trimmed_median(rates)          → predicted_rate  ← 핵심 문제
├─ mad(rates)                    → mad_val
│
├─ calculate_bid_spread()
│   ├─ select_strategy()         → 항상 "aggressive" (사실상 상수)
│   ├─ select_center_offset()    → -mad_val
│   ├─ generate_bid_spread()     → [center]
│   └─ calculate_single()        → base_price × predicted_rate × (LLR + offset)
│                                               ↑ 이 predicted_rate가 무의미
└─ BidResponse 반환
```

**근본 문제**: 파이프라인 전체가 `predicted_rate`(사정률)를 중심으로 구성되어 있고,
해당 값이 복수예비가격 구조상 무작위에 가까워(avg≈1.0, std≈0.007) 의사결정에 기여하지 못함.

---

## 2. 모듈별 판정

### 백엔드

| 모듈 | 판정 | 이유 |
|------|------|------|
| `statistics.py` | **유지** | `trimmed_median()`, `mad()`은 offset 분포 계산에 그대로 재사용 가능 |
| `digit_filter.py` | **유지** | 투찰가 끝자리 회피 — 새 엔진에서도 필요 |
| `normalize.py` | **유지** | 공종/지역/입찰방식 정규화 — 모든 수집/조회 경로에서 계속 사용 |
| `models.py` | **유지** (구조 변경 없음) | `BidParticipants`가 핵심 테이블로 승격 |
| `crud.py` | **부분 유지** | `get_collected_dates()`만 유지. `get_rates_*` 함수들은 deprecated 대상 |
| `crud_write.py` | **유지** | 수집 write 로직 변경 없음 |
| `fallback.py` | **Deprecated** | 사정률 계층형 fallback 전체 불필요 |
| `data/fallback.py` | **Deprecated** | 위와 동일 |
| `calculator.py` | **Deprecated** | `predicted_rate` 의존 공식. 신규 엔진에서 `base_price × (LLR + offset)`로 대체 |
| `strategy.py` | **Deprecated** | `select_strategy()`가 상수 반환. 전략 선택은 UI로 이전 |
| `api/v1/bidding.py` | **유지 (동결)** | 기존 엔드포인트 그대로 동결. 신규 기능 추가 없음 |
| `api/v1/stats.py` | **유지** | 관리 대시보드 API. `GET /stats/distribution`의 데이터 의미가 신규와 다름을 주의 |
| `schemas/request.py` | **유지** | 기존 `BidRequest` 변경 없음 |
| `schemas/response.py` | **유지 (동결)** | 기존 응답 스키마 동결 |

### 프론트엔드

| 모듈 | 판정 | 이유 |
|------|------|------|
| `recharts` (라이브러리) | **유지** | v2.15.4 이미 설치. 신규 그래프에 추가 설치 불필요 |
| `RateDistribution.tsx` | **유지** | 사정률 분포 조회 페이지. 신규 distribution과 데이터 별개 |
| `BidCalculator.tsx` | **유지 (동결)** | 기존 calculate API 화면 그대로 유지 |
| `api.ts` | **부분 수정** | `getBidDistribution()` 함수 및 타입 추가 |
| `AppSidebar.tsx` | **수정** | "분포 분석" 메뉴 항목 추가 |

---

## 3. Distribution Engine 삽입 위치

```
app/
├─ api/v1/
│   ├─ bidding.py           ← 동결 (변경 없음)
│   └─ distribution.py      ← 신규: POST /bid/distribution
│
├─ engine/
│   ├─ statistics.py        ← 재사용 (변경 없음)
│   ├─ distribution.py      ← 신규: offset 히스토그램 빌드, my_position 계산
│   ├─ participants.py      ← 신규: 참여자 수 예측 (fallback 패턴 재활용)
│   ├─ digit_filter.py      ← 재사용 (변경 없음)
│   ├─ calculator.py        ← deprecated (동결, 삭제는 나중에)
│   └─ strategy.py          ← deprecated (동결)
│
├─ db/
│   ├─ crud.py              ← get_rates_* deprecated. get_collected_dates 유지
│   └─ crud_distribution.py ← 신규: bid_participants JOIN bids_history 쿼리
│
├─ schemas/
│   ├─ request.py           ← 기존 유지
│   ├─ response.py          ← 기존 유지
│   └─ distribution.py      ← 신규: DistributionRequest, DistributionResponse
│
└─ data/
    └─ fallback.py          ← deprecated (동결)

frontend/src/
├─ lib/api.ts               ← getBidDistribution() 함수 및 타입 추가
├─ pages/
│   ├─ BidCalculator.tsx    ← 기존 유지 (변경 최소화)
│   └─ BidDistribution.tsx  ← 신규: 히스토그램 + 내 위치 인터랙티브 UI
└─ components/AppSidebar.tsx ← 메뉴 항목 추가
```

---

## 4. 기존 Calculate API와의 공존 전략

**공존 방식: 병렬 운영 (Parallel APIs)**

```
/api/v1/bid/calculate     → 기존 엔진 (동결, 제거 안 함)
/api/v1/bid/distribution  → 신규 엔진 (신규 추가)
```

공존이 가능한 이유:
- 두 API는 완전히 독립적인 데이터 소스 사용
  - 기존: `bids_history.adjustment_rate`
  - 신규: `bid_participants.bid_rate`
- DB 쿼리 충돌 없음
- 스키마 충돌 없음

프론트엔드 공존:
- `BidCalculator` 페이지: 현재 구조 유지 (하위 호환)
- `BidDistribution` 페이지: 신규 독립 페이지로 추가
- Sidebar에 "분포 분석" 메뉴 항목 추가
- 중기적으로 두 페이지를 탭으로 통합 가능 (당장은 분리 유지 권장)

---

## 5. 핵심 데이터 흐름 변화

**기존:**
```
bids_history.adjustment_rate
  → trimmed_median → predicted_rate
  → base_price × predicted_rate × (LLR + offset)
  → 투찰가 1개
```

**신규:**
```
bid_participants.bid_rate
  JOIN bids_history.lower_limit_rate
  → offset = bid_rate - lower_limit_rate
  → 0.1% 간격 히스토그램 빌드
  → 사용자 입력 투찰가 → my_offset
  → 분포상 위치(percentile) + 낙찰확률 표시
```

---

## 6. 즉각 제거 대상 vs 동결 대상

### 즉각 제거 가능 (신규 엔진과 무관한 데드 코드)

- `ClientStatistics` 모델 관련 통계 캐시 로직 (현재도 미사용)
- `select_strategy()` 내 safe/normal 분기 (항상 aggressive 반환)

### 동결 (당분간 유지, 나중에 제거)

- `calculator.py`, `strategy.py`
- `fallback.py`, `data/fallback.py`
- `crud.py`의 `get_rates_*` 함수들
- `BidResponse`의 `predicted_rate`, `mad_value`, `confidence_grade` 필드

---

## 7. 프론트엔드 그래프 스택 적합성

Recharts `2.15.4` 이미 설치. `RateDistribution.tsx`에서 이미 `BarChart + ReferenceLine` 패턴 사용 중.

신규 Distribution 그래프에 필요한 Recharts 컴포넌트:

| 컴포넌트 | 용도 | 기존 사용 여부 |
|----------|------|----------------|
| `BarChart` | 참여자 분포 막대 그래프 | 기존 패턴 재사용 |
| `ReferenceLine` | 내 위치 세로선 | 기존 패턴 재사용 |
| `Cell` | 낙찰 집중 구간 초록 하이라이트 | 신규 추가 필요 |
| `Tooltip` (커스텀) | "N명 참여, M번 낙찰 (X%)" | 커스터마이징 필요 |

**결론: 라이브러리 추가 없이 구현 가능.**

---

## 8. 신규 모듈 명세 요약

### `app/engine/distribution.py`

```python
def build_offset_distribution(rows: list[dict]) -> list[BucketItem]:
    # offset = bid_rate - lower_limit_rate
    # 0.1% 간격 히스토그램 빌드
    # 적격심사 + 복수예비가격 필터는 쿼리 단에서 처리

def calc_my_position(my_bid_price, base_price, lower_limit_rate, distribution) -> Position:
    # my_offset ≈ (my_bid_price / base_price) - lower_limit_rate

def estimate_win_prob(offset_pct: float, distribution: list[BucketItem]) -> float:
    # win_count / count for the matching bucket
```

### `app/engine/participants.py`

```python
async def estimate_participants(db, client_name, region, project_type, bucket_id) -> int:
    # 유사 공고들의 과거 참여자 수 평균
    # Fallback: 발주처 → 지역 → 공종+버킷 → 전체
```

### `app/db/crud_distribution.py`

```python
async def get_offset_distribution(db) -> list[dict]:
    # bid_participants JOIN bids_history
    # WHERE bid_type='적격심사' AND price_method='복수예비가격'
    # SELECT (bid_rate - lower_limit_rate) as offset, is_winner

async def get_avg_participants(db, client_name, region, project_type, bucket_id) -> int:
    # bids_history에서 유사 조건의 participants 평균
```

### `POST /api/v1/bid/distribution` 요청/응답

```
Request:
  bid_notice_id:  str
  overrides:      BidOverrides | null
  my_bid_price:   int | null

Response:
  base_price:             int
  lower_limit_rate:       float
  estimated_participants: int
  distribution: [
    { offset_pct: float, count: int, win_count: int }
  ]
  my_position: {
    offset_pct:           float
    estimated_price:      int
    percentile:           float
    estimated_win_prob:   float
  } | null
```
