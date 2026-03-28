# Bidding Engine MVP Design

## 1. System Overview

### 복수예가(複數豫價) 낙찰 메커니즘 이해

> 이 시스템이 동작하는 입찰 구조를 이해해야 전략이 의미있다.

```
[복수예가 15개 방식 — 현행]

1. 발주처가 100%를 기준으로 복수예가 15개를 생성
   (보통 100% 미만 7개 + 100% 초과 8개 분포)

2. 개찰 시 조달청 컴퓨터가 15개 중 2개를 무작위 선택

3. 입찰 참여자들은 금액을 모르는 상태에서 번호를 무작위 선택

4. 가장 많이 선택된 번호 4개의 평균 → 낙찰 1순위 기준금액 확정

5. 이 기준금액에 가장 가깝게(낙찰하한율 이상) 써낸 업체 낙찰
```

> **핵심 분석 포인트**: 사정률(%) 빈도 분포와 1순위 기준금액 차이를 금액으로 환산해 분석.
> 단순 확률이 아닌 **분산을 줄이고 등수를 안정화**하는 것이 목표.

---

### 핵심 목적

> **이 모델이 예측하는 유일한 변수는 `사정률(Adjustment Rate)`이다.**
> 하한율(≈87.745%)과 기초금액은 API로 취득 가능하지만, 사정률은 개찰 전까지 비공개되는 비밀 난수이다.
> 사정률을 정확히 예측할수록 예정가격 추정치가 정확해지고, 하한가 직전 타점을 노릴 수 있다.

### 최종 투찰 공식

> 모든 계산의 최종 목표는 아래 공식을 통해 원화(KRW) 투찰가를 산출하는 것이다.

$$\text{Final Bid Price} = \text{Base Price} \times \text{Trimmed Median Rate} \times (\text{Lower Limit Rate} + \text{Offset})$$

| 변수 | 공개 여부 | 설명 | 출처 |
| :--- | :--- | :--- | :--- |
| **Base Price** | ✅ 공개 | 기초금액 (원) | 나라장터 API |
| **Lower Limit Rate** | ✅ 공개 | 하한율 (≈ **87.745% 고정**) | 나라장터 API |
| **Trimmed Median Rate** | ❌ 비공개 | 사정률 예측값 | **이 모델이 산출** |
| **Offset** | — | 경쟁자 수 / MAD 기반 전략값 | Strategy Engine |

### 기본 흐름

```
입찰 데이터
   ↓
통계 분석 엔진
   ↓
투찰 전략 계산
   ↓
추천 투찰가 출력 (원화 + 비율)
```

---

# 2. System Architecture

```
┌─────────────────────┐
│ Input Layer         │
│ 입찰 공고 입력      │  ← base_price, lower_limit_rate, participants
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│ Data Processing     │
│ 공종 / 금액 버킷    │  ← project_type, bucket_id
│ 발주처 Fallback     │  ← client → region → type+bucket → global
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│ Statistical Engine  │
│ Trimmed Median      │  ← 상·하위 5% 제거 후 중앙값
│ MAD 계산            │  ← 극단값 내성 분산 측정
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│ Strategy Engine     │
│ Offset 선택         │  ← 경쟁자 수 기반 Safe / Normal / Aggressive
│ Digit Filter 적용   │  ← .000 / .500 / .745 / .777 등 블랙리스트
└─────────┬───────────┘
          ↓
┌─────────────────────┐
│ Output Engine       │
│ 원화 투찰가 계산    │  ← Base × Median × (LLR + Offset)
│ 비율(%) 병기        │
└─────────────────────┘
```

---

# 3. Database Schema

## bids_history

과거 입찰 결과 데이터

| 컬럼 | 타입 | 설명 |
| :--- | :--- | :--- |
| id | INTEGER PK | |
| project_id | TEXT | 공고 번호 |
| client_name | TEXT | 발주처 명 |
| region | TEXT | 지역 |
| project_type | TEXT | 공종 (실내건축 / 조경 / …) |
| base_price | BIGINT | 기초금액 (원) |
| lower_limit_rate | FLOAT | 하한율 (예: 0.8724) |
| adjustment_rate | FLOAT | 실제 사정률 (결과값) |
| winner_price | BIGINT | 낙찰가 (원) |
| participants | INTEGER | 참여 업체 수 |
| date | DATE | 개찰 일자 |

---

## client_statistics

발주처별 사정률 통계 (캐싱 용도)

| 컬럼 | 타입 | 설명 |
| :--- | :--- | :--- |
| client_name | TEXT PK | |
| project_type | TEXT | 공종 |
| bucket_id | INTEGER | 금액 구간 |
| median_rate | FLOAT | Trimmed Median 사정률 |
| mad_rate | FLOAT | MAD 값 |
| sample_size | INTEGER | 사용된 데이터 수 |
| last_updated | DATETIME | |

> **Fallback 우선순위:** 발주처(≥20건) → 지역 → 공종+버킷 → 전체

---

## project_bucket

금액 구간 정의

| bucket_id | min | max | description |
| :--- | :--- | :--- | :--- |
| 1 | 0 | 1억 | 소형 (초정밀 경쟁) |
| 2 | 1억 | 5억 | 표준 |
| 3 | 5억 | 20억 | 중형 |
| 4 | 20억 | ∞ | 대형 (보수적 투찰) |

---

# 4. Core Algorithm

## Step-by-Step

```
1.  입찰 공고 입력
      - base_price, lower_limit_rate, participants, project_type

2.  공종 확인 → 데이터 풀 분리
      - "실내건축" / "조경" 등 혼합 절대 금지

3.  금액 버킷 결정
      - base_price 기준 bucket_id 선택

4.  발주처 통계 조회 (Fallback 포함)
      - client_statistics 에서 median_rate, mad_rate 로드
      - sample_size < 20 이면 다음 단계로 Fallback

5.  Trimmed Median 계산
      - bids_history 에서 adjustment_rate 수집
      - 상위 5% / 하위 5% 제거 후 중앙값 계산

6.  MAD 계산
      - MAD = Median(|rate_i - Median|)
      - 신뢰 범위: [Median - MAD, Median + MAD]

7.  경쟁자 수 기반 전략 선택
      - participants < 50   → Safe     offset = +MAD
      - 50 ≤ p < 300        → Normal   offset = 0
      - participants ≥ 300  → Aggressive offset = -MAD

8.  Offset Range 생성 (동가 회피용 미세 분산)
      - [Median - 0.001, Median, Median + 0.001] 중 전략에 따라 선택

9.  Digit Filter 적용
      - 소수점 끝자리 블랙리스트: .000 / .500 / .745 / .777
      - 해당 시 인접한 안전 숫자로 Shift

10. 최종 투찰가 계산
      -- 사정률(Trimmed Median)은 모델이 예측, 하한율은 API 수집(≈ 0.87745 고정)
      Final Bid Price = base_price × predicted_rate × (lower_limit_rate + offset)

11. 추천가 리스트 출력
      - 원화(KRW) + 예가 대비 비율(%) 병기
```

---

# 5. Strategy Rules

### 타겟 범위

기존 97~103% 범위에서 **98~101%** 수준으로 타겟 범위 축소.
100%를 기준으로 **방향성 예측**이 핵심: 발주처 패턴에 따라 이번 건은 100% 상단/하단 중 어느 쪽을 노릴지 결정.

```
예) 성남시 조경 공사 → 과거 데이터상 100% 미만 집중 → Aggressive 전략 우선
```

| 전략 | 조건 | Offset | 목적 |
| :--- | :--- | :--- | :--- |
| **Safe** | participants < 50 | `+MAD` | 마진 확보, 예가 초과 방지 |
| **Normal** | 50 ≤ p < 300 | `0` | 기본 궤적 추종 |
| **Aggressive** | participants ≥ 300 | `-MAD` | 하단 타격, 낙찰 확률 극대화 |

> **Safe Bid 공식:** `Base × Median × (LLR + MAD)`
> **Aggressive Bid 공식:** `Base × Median × (LLR - MAD)`

### 성과 목표 (2026 기준)

| 지표 | 현재 | 목표 |
| :--- | :--- | :--- |
| 낙찰률 | 0.3~0.4% (1,000건 중 3~4건) | 1% 이상 (3배 향상) |
| 타겟 범위 | 97~103% | 98~101% |
| 예측 방식 | 단순 빈도 분포 | 발주처별 방향성 예측 + 분산 안정화 |

### 주요 타겟 발주처

| 발주처 | 특징 | 전략 |
| :--- | :--- | :--- |
| **국방부** | 연말 집중 발주 | 시즌 집중 공략 |
| **교육청** | 연중 높은 빈도 | 지속 모니터링 |
| **경기도 지자체** | 조경·실내건축 물량 다수 | 발주처 단위 패턴 분석 |

---

# 6. Output Format

추천 투찰가는 **3가지 전략값**을 출력하며 원화와 비율을 병기한다.

```
입력 정보
  기초금액     : 1,000,000,000 원
  하한율       : 0.8724
  경쟁자 수    : 152명  →  Normal 전략 적용

──────────────────────────────────────────
[ Aggressive Bid ]
  사정률 비율  : 87.736 %  (Median - MAD)
  최종 투찰가  :   876,234,000 원

[ Normal Bid ]
  사정률 비율  : 87.746 %  (Median)
  최종 투찰가  :   877,460,000 원

[ Safe Bid ]
  사정률 비율  : 87.756 %  (Median + MAD)
  최종 투찰가  :   878,686,000 원
──────────────────────────────────────────
⚠ Digit Filter 적용: .000 → .234 로 Shift 완료
```

---

# 7. Key Design Principles

1. **공식 우선** — 모든 출력은 `Base × Median × (LLR + Offset)` 공식으로 귀결
2. **발주처 패턴** — 발주처 단위 통계를 최우선, 데이터 부족 시 계층적 Fallback
3. **Trimmed Median** — 상·하위 5% 제거로 노이즈 내성 확보
4. **MAD** — 표준편차 대신 극단값에 강건한 분산 측정
5. **동적 Offset** — 경쟁자 수에 따라 전략 자동 전환
6. **Digit Filter** — 게으른 끝자리(.000/.500 등) 자동 회피
7. **원화 출력** — 비율(%) 뿐만 아니라 실제 투찰 가능한 원화 금액 필수 제공

---

# 8. Tech Stack

| 레이어 | 기술 | 역할 |
| :--- | :--- | :--- |
| **API Server** | FastAPI (Python) | 투찰가 계산 요청 처리, 나라장터 API 연동 |
| **Statistical Engine** | Python (numpy / scipy) | Trimmed Median, MAD, Offset 계산 |
| **Database** | PostgreSQL | 입찰 이력, 발주처 통계, 금액 버킷 저장 |
| **ORM** | SQLAlchemy + Alembic | DB 모델링 및 마이그레이션 |
| **Validation** | Pydantic | 요청/응답 스키마 검증 |

---

# 9. Project Structure

```
gonggong/
├── app/
│   ├── main.py                  # FastAPI 앱 진입점
│   ├── api/
│   │   └── v1/
│   │       └── bidding.py       # POST /bid/calculate 엔드포인트
│   │
│   ├── engine/
│   │   ├── statistics.py        # trimmed_median(), mad() 계산
│   │   ├── strategy.py          # offset 선택, 전략 결정
│   │   ├── digit_filter.py      # Digit Filter (블랙리스트 회피)
│   │   └── calculator.py        # 최종 투찰가 조합 및 출력
│   │
│   ├── data/
│   │   ├── fetcher.py           # 나라장터 API 호출 (기초금액, 하한율 등)
│   │   └── fallback.py          # 발주처 → 지역 → 공종+버킷 → 전체 Fallback
│   │
│   ├── db/
│   │   ├── models.py            # SQLAlchemy 모델 (bids_history 등)
│   │   ├── crud.py              # DB 조회/저장 로직
│   │   └── session.py           # DB 세션 관리
│   │
│   └── schemas/
│       ├── request.py           # BidRequest (Pydantic)
│       └── response.py          # BidResponse (Pydantic)
│
├── alembic/                     # DB 마이그레이션
├── tests/
│   ├── test_statistics.py
│   ├── test_strategy.py
│   └── test_calculator.py
│
├── .env                         # DB URL, API 키 등
├── requirements.txt
└── README.md
```

---

# 10. API Design

## `POST /api/v1/bid/calculate`

API는 두 가지 동작 모드를 단일 엔드포인트로 처리한다.

---

### Mode 1 — Auto-Fetch (기본 동작)

클라이언트는 공고 번호만 전달. 나머지는 G2B Fetcher가 자동 처리.

**Request**
```json
{
  "bid_notice_id": "2026031112345"
}
```

**Backend Flow**
```
bid_notice_id 수신
  ↓
G2B Fetcher → 나라장터 OpenAPI 호출
  ↓
공고문 파싱 (base_price, client_name, project_type, lower_limit_rate 등)
  ↓
통계 모델 주입 → 타점 계산
  ↓
추천 투찰가 응답
```

**장점:** 사용자 피로도 제로, 입력 실수 원천 차단

---

### Mode 2 — Manual Override (시뮬레이션 / 장애 대응)

G2B API 다운 시 수동 대응, 또는 입찰 담당자의 사전 시뮬레이션 용도.

`overrides` 필드에 값이 존재하면 G2B에서 가져온 해당 값을 **즉시 덮어쓴다.**

**Request**
```json
{
  "bid_notice_id": "2026031112345",
  "overrides": {
    "base_price": 950000000,
    "lower_limit_rate": 87.745
  }
}
```

**Backend Flow**
```
bid_notice_id 수신
  ↓
G2B Fetcher → 나라장터 OpenAPI 호출 (시도)
  ↓
overrides 키 존재? → YES: 해당 필드 덮어쓰기 / NO: 그대로 사용
  ↓
통계 모델 주입 → 타점 계산
  ↓
추천 투찰가 응답 (overridden 여부 명시)
```

**장점:** G2B 장애 시 수동 대응, 강력한 사전 시뮬레이션 툴

---

### Response (공통)

```json
{
  "bid_notice_id": "2026031112345",
  "mode": "auto",
  "overridden_fields": [],
  "fetched": {
    "base_price": 1000000000,
    "client_name": "서울특별시",
    "project_type": "실내건축",
    "lower_limit_rate": 0.87745,
    "participants": 152
  },
  "strategy": "normal",
  "predicted_rate": 0.99812,
  "bids": [
    { "label": "Aggressive", "rate_pct": 87.736, "price_krw": 876234000 },
    { "label": "Normal",     "rate_pct": 87.746, "price_krw": 877460000 },
    { "label": "Safe",       "rate_pct": 87.756, "price_krw": 878686000 }
  ],
  "digit_filter_applied": true,
  "fallback_level": "client"
}
```

> `"mode"`: `"auto"` | `"override"`  
> `"overridden_fields"`: Override된 필드명 목록 (예: `["base_price", "lower_limit_rate"]`)

```
