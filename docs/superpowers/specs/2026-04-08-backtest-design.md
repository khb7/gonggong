# 백테스트 설계 — 투찰가 예측 정확도 검증

작성일: 2026-04-08

---

## 목적

`bids_history` DB에 쌓인 실제 낙찰 데이터를 활용해 현재 예측 엔진의 정확도를 측정한다.

측정 지표 두 가지:
1. **사정률 오차** — `|predicted_rate - actual_rate|` 가 얼마나 작은가
2. **낙찰 구간 진입율** — 계산된 투찰가가 `낙찰하한가 ≤ 투찰가 ≤ 예정가격` 범위 안에 드는가

---

## 데이터 분할 (시간 기준)

| 구분 | 기간 | 목적 |
|------|------|------|
| 학습셋 | 2023-01-01 ~ 2024-12-31 | fallback 통계 계산에 사용 |
| 검증셋 | 2025-01-01 ~ 현재 | 예측 대상 (약 6,900건) |

랜덤 분할 대신 시간 기준을 사용하는 이유: 실제 운영에서는 과거 데이터로 미래를 예측하므로 데이터 누수 방지.

---

## 변경 범위

### 1. `app/db/crud.py` — before_date 파라미터 추가

기존 4개 함수에 `before_date: date | None = None` 파라미터 추가:
- `get_rates_by_client`
- `get_rates_by_region`
- `get_rates_by_type_and_bucket`
- `get_all_rates`

`before_date`가 있으면 `WHERE bid_date < before_date` 조건 추가. `None`이면 기존 동작 그대로.

DB 스키마/마이그레이션 변경 없음. 기존 API 동작 영향 없음.

### 2. `scripts/backtest.py` — 백테스트 스크립트 (신규)

처리 흐름:
```
1. DB에서 2025-01-01 이후 레코드 전부 조회 (검증셋)
2. 각 레코드마다:
   a. before_date=2025-01-01 로 fallback 호출 → predicted_rate, MAD, fallback_level
   b. 실제 adjustment_rate와 사정률 오차 계산
   c. 투찰가 계산 → 낙찰 구간 진입 여부 판단
3. 결과를 CSV로 저장
4. 공종별 집계 → MD 리포트 생성
```

낙찰 구간 진입 판단:
```
예정가격  = base_price × actual_adjustment_rate
낙찰하한가 = 예정가격 × lower_limit_rate
진입 여부  = 낙찰하한가 ≤ 투찰가 ≤ 예정가격
```

---

## 출력물

### CSV (`data/backtest_YYYYMMDD.csv`)

| 컬럼 | 설명 |
|------|------|
| project_id | 공고번호 |
| client_name | 발주처 |
| project_type | 공종 |
| base_price | 기초금액 |
| actual_rate | 실제 사정률 |
| predicted_rate | 예측 사정률 |
| rate_error | `abs(predicted - actual)` |
| bid_price | 계산된 투찰가 |
| in_range | 낙찰 구간 진입 여부 (True/False) |
| fallback_level | 사용된 fallback 레벨 |
| bid_date | 개찰일 |

### MD 리포트 (`data/backtest_YYYYMMDD.md`)

```
# 백테스트 리포트 — YYYY-MM-DD

## 전체 요약
- 검증 건수 / 평균 사정률 오차 / 낙찰 구간 진입율

## 건축
- 평균 오차 / 중간값 오차 / 구간 진입율 / fallback 분포
- 오차 큰 케이스 TOP5 표

## 조경
- (건축과 동일 구조)

## 결론
- 잘 맞는 구간 / 취약한 구간 한 줄 요약
```

---

## 파일 구조

```
app/db/crud.py          ← before_date 파라미터 추가 (기존 파일 수정)
scripts/backtest.py     ← 백테스트 메인 스크립트 (신규)
data/
  backtest_YYYYMMDD.csv ← 건별 상세 결과
  backtest_YYYYMMDD.md  ← 요약 리포트
```

---

## 실행 방법

```bash
python scripts/backtest.py
# 또는 검증 구간 직접 지정
python scripts/backtest.py --since 2025-01-01
```
