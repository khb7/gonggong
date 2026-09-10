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
