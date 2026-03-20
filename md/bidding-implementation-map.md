# 입찰 모델 구현 매핑 가이드 (Bidding Implementation Map)

이 문서는 `md/공공입찰.md`에 정의된 10단계 투찰 로직이 실제 프로젝트의 어떤 코드 파일과 함수에 대응되는지 정리한 매핑 가이드입니다.

---

## 1. 데이터 분리 (Data Isolation)
*   **요구사항**: 공종 분리 및 금액 구간 분리 (Size Bucketing)
*   **구현 파일**: [app/db/crud.py](file:///c:/Users/Lenovo/gonggong/app/db/crud.py)
*   **핵심 로직**:
    *   `_BUCKET_RANGES`: 금액별 구간(1억, 5억, 20억) 정의
    *   `_bucket_filter()`: SQL 쿼리 시 금액 구간 필터링 조건 생성

## 2. 발주처 패턴 모델 (Issuer Pattern Model)
*   **요구사항**: 계층적 Fallback 구조 (발주처 → 지역 → 공종+금액 → 전체)
*   **구현 파일**: [app/data/fallback.py](file:///c:/Users/Lenovo/gonggong/app/data/fallback.py)
*   **핵심 로직**:
    *   `get_rates_with_fallback()`: 데이터 수(20건 이상)에 따른 계층별 조회 순서 제어

## 3. 극단값 제거 (Trimmed Median)
*   **요구사항**: 상/하위 5% 제거 후 중앙값 계산
*   **구현 파일**: [app/engine/statistics.py](file:///c:/Users/Lenovo/gonggong/app/engine/statistics.py)
*   **핵심 로직**:
    *   `trimmed_median()`: 데이터를 정렬하여 상/하위 일정 비율을 제외한 구간의 중앙값 산출

## 4. 분산 계산 (MAD)
*   **요구사항**: 극단값에 강건한 MAD(Median Absolute Deviation) 사용
*   **구현 파일**: [app/engine/statistics.py](file:///c:/Users/Lenovo/gonggong/app/engine/statistics.py)
*   **핵심 로직**:
    *   `mad()`: 편차들의 중앙값을 계산하여 데이터의 흩어짐 정도를 측정
    *   `confidence_range()`: [Median - MAD, Median + MAD] 범위 산출

## 5. 오프셋 범위 (Offset Range)
*   **요구사항**: 단일값 탈락 위험 방지를 위한 범위형 오프셋 생성
*   **구현 파일**: [app/engine/strategy.py](file:///c:/Users/Lenovo/gonggong/app/engine/strategy.py)
*   **핵심 로직**:
    *   `generate_bid_spread()`: 중심점 기준 일정 간격(`step`)의 오프셋 후보군 리스트 생성

## 6. 경쟁자 기반 동적 룰 (Competitor Count Rule)
*   **요구사항**: 참여 업체 수에 따른 전략 변경 (Safe, Normal, Aggressive)
*   **구현 파일**: [app/engine/strategy.py](file:///c:/Users/Lenovo/gonggong/app/engine/strategy.py)
*   **핵심 로직**:
    *   `select_strategy()`: 경쟁자 수(50명, 300명 기준)에 따라 전략 문자열 결정

## 7. 전략 모드 (Strategy Mode)
*   **요구사항**: Safe Bid (+MAD), Aggressive Bid (-MAD) 적용
*   **구현 파일**: [app/engine/strategy.py](file:///c:/Users/Lenovo/gonggong/app/engine/strategy.py)
*   **핵심 로직**:
    *   `select_center_offset()`: 선택된 전략에 따라 MAD를 더하거나 뺄 중심 오프셋 결정

## 8. Digit Filter (동가 회피)
*   **요구사항**: 비정상적으로 많이 쓰이는 소수점 끝자리 블랙리스트 회피
*   **구현 파일**: [app/engine/digit_filter.py](file:///c:/Users/Lenovo/gonggong/app/engine/digit_filter.py)
*   **핵심 로직**:
    *   `DIGIT_BLACKLIST`: `000`, `500`, `745`, `777` 등 관리
    *   `apply_digit_filter()`: 소수점 끝 3자리가 블랙리스트면 안전한 숫자로 시프트

## 9. 최종 투찰 공식
*   **요구사항**: `Final Bid Price = Base Price * Predicted Rate * (Lower Limit Rate + Offset)`
*   **구현 파일**: [app/engine/calculator.py](file:///c:/Users/Lenovo/gonggong/app/engine/calculator.py)
*   **핵심 로직**:
    *   `calculate_single()`: 공식을 적용하여 실질 투찰 금액(원화) 및 투찰 비율(%) 산출

## 10. 최종 프로세스 (Workflow)
*   **요구사항**: 입력부터 다중 타점 포트폴리오 출력까지의 흐름
*   **구현 파일**: [app/engine/calculator.py](file:///c:/Users/Lenovo/gonggong/app/engine/calculator.py)
*   **핵심 로직**:
    *   `calculate_bid_spread()`: 모든 구성 요소를 조합하여 단일 공고에 대한 최종 투찰가 리스트 생성
