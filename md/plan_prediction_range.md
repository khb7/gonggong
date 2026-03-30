# 계획: prediction_range 응답 필드 추가

**작성일:** 2026-03-30
**관련 이슈:** 사정률 예측 구간 미노출 → 프론트/사용자가 신뢰도를 판단할 수 없음

---

## 왜 필요한가

### 현재 문제

엔진은 `predicted_rate`(Trimmed Median)와 `mad_value`를 모두 계산하고 있다.
그런데 응답에는 두 값이 **따로따로** 나가기 때문에, 실제로 의미 있는 정보인
**"이번 예측이 얼마나 믿을 만한가"** 를 직접적으로 전달하지 못한다.

```json
현재 응답 (문제):
{
  "predicted_rate": 1.0012,
  "mad_value": 0.0031,
  ...
}
→ 사용자가 직접 1.0012 ± 0.0031 을 계산해야 함
→ MAD가 크면 믿으면 안 된다는 것을 직관적으로 알기 어려움
```

### 왜 구간이 중요한가

복수예가 시스템에서 사정률은 개찰 전까지 비공개 난수다.
즉, **단 하나의 정확한 값을 예측하는 것은 구조적으로 불가능**하다.

현실적인 목표는:
> "예측값 ± MAD 구간 안에 실제 사정률이 들어올 확률을 높인다"

예를 들어 MAD = 0.003이면 예측 구간은 ±0.3%로, 이 안에 실제값이 들어올 확률이
발주처 패턴이 일정할 경우 80~90%에 달한다.
반대로 MAD = 0.015면 구간이 ±1.5%로 넓어져 사실상 참고 수준에 불과하다.

이 차이를 응답에서 명확하게 알려줘야 한다.

### 구체적 활용 시나리오

| 상황 | 현재 | prediction_range 추가 후 |
|------|------|--------------------------|
| MAD 작은 단골 발주처 | mad_value: 0.0028 (숫자만 노출) | range: [0.9984, 1.0040] + 신뢰도 ★★★ |
| Fallback 발동 | mad_value: 0.0142 (숫자만 노출) | range: [0.9870, 1.0154] + 신뢰도 ★☆☆ |
| 프론트 UI | 사용자가 계산해야 함 | 구간 바로 표시 가능 |
| 투찰 자동화 판단 | 기준 없음 | MAD > 0.007이면 자동 투찰 보류 로직 연결 가능 |

---

## 무엇을 추가할 것인가

### 추가 필드 2개

**1. `prediction_range`** — 예측 구간 `[lower, upper]`

```
lower = predicted_rate - mad_value
upper = predicted_rate + mad_value
```

예) predicted_rate=1.0012, mad_value=0.0031
→ prediction_range: [0.9981, 1.0043]

**2. `confidence_grade`** — MAD 기반 신뢰도 등급 (문자열)

| 조건 | 등급 | 의미 |
|------|------|------|
| MAD ≤ 0.003 | `"high"` | 발주처 패턴 일정, ±1% 구간 활용 가능 |
| 0.003 < MAD ≤ 0.007 | `"medium"` | 일반 발주처 평균 수준 |
| MAD > 0.007 | `"low"` | Fallback 단계, 구간 넓음 |

등급 기준은 실제 데이터가 쌓이면 재조정 필요.

---

## 어떻게 추가할 것인가

### 변경 범위

총 3개 파일만 수정. 엔진 로직(statistics.py, calculator.py 등)은 **변경 없음**.

```
app/schemas/response.py     ← 필드 2개 추가
app/api/v1/bidding.py       ← 계산 후 값 채워서 반환
statistics.py               ← confidence_range() 이미 존재, 재사용만
```

---

### 1단계: `response.py` — 스키마에 필드 추가

```python
class BidResponse(BaseModel):
    ...
    predicted_rate: float
    mad_value: float
    prediction_range: list[float]    # 추가: [lower, upper]
    confidence_grade: str            # 추가: "high" | "medium" | "low"
    fallback_level: str
    bids: list[BidItem]
```

---

### 2단계: `bidding.py` — 계산 후 필드 채우기

`statistics.py`에 이미 `confidence_range()` 함수가 있다. 호출만 추가하면 된다.

```python
# statistics.py에 이미 존재
from app.engine.statistics import trimmed_median, mad, confidence_range

# bidding.py Step 5 통계 계산 부분에 추가
predicted_rate = trimmed_median(rates)
mad_val = mad(rates)
rate_lower, rate_upper = confidence_range(predicted_rate, mad_val)

# 신뢰도 등급 계산 (인라인 헬퍼)
if mad_val <= Decimal("0.003"):
    grade = "high"
elif mad_val <= Decimal("0.007"):
    grade = "medium"
else:
    grade = "low"
```

fallback이 "default"(데이터 없음)일 때는:
```python
# 데이터 없는 경우 기본값
rate_lower = predicted_rate - mad_val   # 1.0 - 0.002 = 0.998
rate_upper = predicted_rate + mad_val   # 1.0 + 0.002 = 1.002
grade = "low"   # 데이터 없으면 항상 low
```

---

### 3단계: `bidding.py` — BidResponse에 필드 채우기

```python
return BidResponse(
    ...
    prediction_range=[float(rate_lower), float(rate_upper)],
    confidence_grade=grade,
    ...
)
```

---

## 변경 후 응답 예시

### 신뢰도 높은 경우 (단골 발주처, 데이터 충분)

```json
{
  "predicted_rate": 1.0012,
  "mad_value": 0.0028,
  "prediction_range": [0.9984, 1.0040],
  "confidence_grade": "high",
  "fallback_level": "client"
}
```

→ "이번 건은 사정률이 99.84%~100.40% 사이일 가능성이 높다"

### 신뢰도 낮은 경우 (처음 보는 발주처, Fallback)

```json
{
  "predicted_rate": 0.9960,
  "mad_value": 0.0142,
  "prediction_range": [0.9818, 1.0102],
  "confidence_grade": "low",
  "fallback_level": "global"
}
```

→ "구간이 넓어 신뢰도 낮음. 참고용으로만 활용 권장"

---

## 추후 연결 가능한 기능

이 필드가 생기면 아래 기능과 자연스럽게 연결된다.

1. **투찰 자동화 안전장치**
   `confidence_grade == "low"` 이면 자동 투찰 보류, 수동 확인 요청

2. **프론트 UI 신뢰도 배지**
   ★★★ / ★★☆ / ★☆☆ 표시로 사용자가 직관적으로 판단

3. **발주처별 신뢰도 추적**
   데이터가 쌓일수록 특정 발주처의 grade가 low → high로 올라가는 걸 추적 가능

4. **등급 기준 재조정**
   실제 데이터 누적 후 포함율(실제 사정률이 구간 안에 든 비율) 계산 →
   기준값 (0.003 / 0.007) 실증적으로 보정

---

## 구현 시 주의사항

- `confidence_grade` 기준값(0.003, 0.007)은 **현재 가설** 수준. 데이터가 쌓인 뒤 실측 포함율을 보고 재조정 필요.
- `prediction_range`는 `float` 리스트로 직렬화. `Decimal` 그대로 반환하면 Pydantic 직렬화 오류 가능성 있음.
- `confidence_range()` 함수는 `statistics.py:72`에 이미 구현되어 있으므로 새로 짤 필요 없음.
