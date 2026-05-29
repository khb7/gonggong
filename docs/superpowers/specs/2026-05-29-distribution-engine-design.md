# 분포 기반 투찰가 엔진 재설계

**날짜**: 2026-05-29  
**상태**: 승인 대기  
**배경**: 기존 사정률 예측 엔진의 한계 확인 후 경쟁자 분포 기반으로 전환

---

## 1. 문제 정의

### 기존 엔진의 한계

데이터 분석 결과 사정률(예정가격/기초금액)은 **무작위에 가까운 분포**임이 확인됨:
- 평균: 0.9995, 표준편차: 0.0072
- 발주처별로 통계 내도 결국 avg≈1.0, std≈0.007 수렴
- 복수예비가격 방식에서 예정가격은 15개 중 무작위 2개 추첨 → 예측 불가

```
기존 흐름: 사정률 예측 → 예정가격 추정 → 투찰가 계산
문제:       사정률이 무작위라 예측이 의미 없음
```

### 실제로 중요한 것

분석 결과(44,044건 참여자 데이터) 에서 확인된 패턴:
- 참여자들은 **낙찰하한율 기준 -2% ~ +1.5%** 구간에 집중
- 낙찰자는 **낙찰하한율 기준 -0.5% ~ -0.8%** 구간에 집중
- 낙찰하한율보다 낮게 낸 업체 중 A값 반영 후 유효한 가장 낮은 가격이 낙찰

---

## 2. 새 엔진 개념

```
기존: 사정률 예측 → 예정가격 → 투찰가 (숫자 1개)
신규: 경쟁자 분포 분석 → 낙찰 확률 지형도 + 내 위치 표시
```

### 핵심 지표: offset

```
offset = 참여자의 bid_rate - lower_limit_rate
       = (투찰금액/예정가격) - (낙찰하한가/예정가격)
       ≈ (투찰금액/기초금액) - 낙찰하한율  [사정률≈1.0 근사]
```

이 offset을 기준으로 모든 과거 데이터를 정규화하면
낙찰하한율이 달라도 범용 분포를 얻을 수 있음.

---

## 3. 아키텍처

### 3-1. 새 API 엔드포인트

```
POST /api/v1/bid/distribution

Request:
  bid_notice_id:  str              # G2B 공고번호
  overrides:      BidOverrides     # 수동 입력 (기초금액, 낙찰하한율 등)
  my_bid_price:   int | null       # 내 투찰가 (원), 선택

Response:
  base_price:             int
  lower_limit_rate:       float
  estimated_participants: int
  distribution: [
    {
      offset_pct:  float   # -3.0 ~ +3.0, 0.1% 간격
      count:       int     # 해당 구간 참여 건수
      win_count:   int     # 해당 구간 낙찰 건수
    }
  ]
  my_position: {
    offset_pct:           float   # 내 가격의 offset
    estimated_price:      int     # 기초금액 × (낙찰하한율 + offset)
    percentile:           float   # 내 가격보다 낮은 참여자 비율
    estimated_win_prob:   float   # 해당 구간 낙찰 확률
  } | null
```

---

### 3-2. 엔진 모듈

```
app/engine/
  distribution.py   ← 신규: 분포 계산 핵심 로직
  participants.py   ← 신규: 참여자 수 예측
  calculator.py     ← 기존 유지 (하위 호환)
  statistics.py     ← 기존 유지
  strategy.py       ← 기존 유지
```

#### `distribution.py` 역할

```python
def build_distribution(db) -> list[BucketItem]:
    """
    전체 bid_participants 데이터에서 offset 분포 빌드.
    - 적격심사 + 복수예비가격 필터
    - offset = bid_rate - lower_limit_rate
    - 0.1% 간격 히스토그램
    """

def calc_my_position(my_bid_price, base_price, lower_limit_rate, distribution) -> Position:
    """
    내 투찰가를 offset으로 변환 후 분포상 위치 계산.
    my_offset ≈ (my_bid_price / base_price) - lower_limit_rate
    """

def estimate_win_prob(offset_pct, distribution) -> float:
    """
    해당 offset 구간의 과거 낙찰 확률 반환.
    win_count / count
    """
```

#### `participants.py` 역할

```python
def estimate_participants(db, client_name, region, project_type, bucket_id) -> int:
    """
    유사 공고들의 과거 참여자 수 평균 반환.
    Fallback: 발주처 → 지역 → 공종+버킷 → 전체
    """
```

---

### 3-3. DB 쿼리

새 쿼리 함수 `app/db/crud_distribution.py`:

```python
async def get_offset_distribution(db) -> list[dict]:
    """
    bid_participants JOIN bids_history
    WHERE bid_type='적격심사' AND price_method='복수예비가격'
    SELECT (bid_rate - lower_limit_rate) as offset, is_winner
    """

async def get_avg_participants(db, client_name, region, project_type, bucket_id) -> int:
    """
    bids_history에서 유사 조건의 participants 평균
    """
```

---

### 3-4. 프론트엔드

기존 계산 화면에 그래프 패널 추가 (React + Recharts).

```
┌──────────────────────────────────────────┐
│  공고번호 입력 / 기본정보                │
│  기초금액: 500,000,000원                 │
│  낙찰하한율: 87.745%                     │
│  예상 참여자: 약 320명                   │
├──────────────────────────────────────────┤
│  [투찰가 입력] 437,500,000 원            │
│         ↕ 실시간 변환                    │
│  offset: -0.50%  | 예상 낙찰확률: 18%   │
├──────────────────────────────────────────┤
│  경쟁자 분포 그래프                      │
│                                          │
│      ████                                │
│  ████████ ████▲내위치                   │
│  ████████████████                        │
│  -2%  -1%   0%  +1%  (offset)           │
│                                          │
│  ■ 참여자  ■ 낙찰자  ▲ 내 위치          │
└──────────────────────────────────────────┘
```

**인터랙션:**
- 투찰가(원) 입력 → offset% 자동 계산 → 그래프에 빨간 세로선 실시간 업데이트
- offset% 직접 입력도 가능 → 원화 자동 변환
- 낙찰자 집중 구간(offset -0.5%~-0.8%) 초록색 하이라이트
- 툴팁: "이 구간: N명 참여, M번 낙찰 (낙찰률 X%)"

---

## 4. 데이터 흐름

```
사용자 입력 (공고번호 or 수동)
    │
    ▼
G2B API → 기초금액, 낙찰하한율
    │
    ▼
distribution.py
  ├─ DB에서 전체 offset 분포 조회 (캐시 가능)
  ├─ 참여자 수 예측 (participants.py)
  └─ my_bid_price → my_position 계산
    │
    ▼
Response → 프론트엔드 그래프 렌더링
```

---

## 5. 기존 엔진과의 관계

- 기존 `/bid/calculate` 엔드포인트 **유지** (하위 호환)
- 새 `/bid/distribution` 엔드포인트 **추가**
- 향후 프론트엔드에서 두 탭으로 제공하거나 통합 가능

---

## 6. 한계 및 향후 개선

| 현재 한계 | 향후 개선 방향 |
|---|---|
| A값 방식 공고는 실제 하한가와 차이 | A값 데이터 수집 후 보정 |
| 71개 공고 기반 (통계 제한적) | 데이터 수집 확대로 정밀도 향상 |
| 공고별 특성 미반영 | 발주처/공종별 분포 분리 (데이터 충분 시) |
| 끝자리 전략 미포함 | 끝자리 블랙리스트 기능 별도 구현 |
