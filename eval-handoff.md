# Handoff — T-038 투찰가 계산: 사정률 직접 입력 + 과거 실제 사정률 분포 그래프 — 2026-09-22

## 변경한 파일
- `app/schemas/request.py` — `BidOverrides.preprice_rate` (Decimal, 0.97~1.03) 추가
- `app/schemas/response.py` — `PrepriceHistogramOut`, `BidResponse.preprice_histogram` 추가, `fallback_level` 설명 갱신
- `app/db/crud.py` — `get_preprice_rates(db)`: (발주처명, preprice_rate) 전부 (16k 행, 51ms)
- `app/engine/preprice_histogram.py` — **신규**. 계약법별 실제 사정률 히스토그램 (97~103%, 0.05%p × 120 bin)
- `app/api/v1/bidding.py` — override 적용 (`fallback_level: "override"`), 히스토그램 동봉
- `frontend/src/lib/preprice.ts` — **신규**. 유효율·근접률·차트 행 계산 (bin 안 균등 가정으로 보간)
- `frontend/src/lib/api.ts` — `PrepriceHistogram` 타입, `BidResult.preprice_histogram`
- `frontend/src/pages/BidCalculator.tsx` — "사정률 (%)" 입력칸, 결과 아래 분포 카드 (유효/근접 숫자 + 막대그래프 + 내 사정률 세로선 + stale 안내)
- `tests/test_preprice_histogram.py`, `tests/test_api_bidding.py`, `frontend/src/lib/preprice.test.ts`, `frontend/src/pages/BidCalculator.test.tsx`
- `CLAUDE.md` (동결 예외 명시), `tasks.md` (T-038), `.claude/launch.json` (로컬 미리보기용)

## Eval 에이전트가 확인해야 할 포인트
- `POST /api/v1/bid/calculate` body 예:
  `{"bid_notice_id":"R26BK01733740-000","overrides":{"base_price":1114200000,"lower_limit_rate":0.88745,"a_value":57702882,"client_name":"경기도 연천군 맑은물관리사업소","preprice_rate":1.005}}`
  → `predicted_rate: 1.005`, `fallback_level: "override"`, `overridden_fields` 에 `preprice_rate`,
  `preprice_histogram.law == "local"`, `n ≈ 11,626`, `counts` 길이 120, 합 == n.
  `preprice_rate` 를 빼면 `predicted_rate: 1.0015`, `fallback_level: "fixed"`.
  `preprice_rate: 0.9` → 422.
- 화면 `/calculator`: 위 값으로 계산 → 투찰가 카드 위에 "사정률 100.15% 로 넣었다면 — 지방계약 ±3% 공고 11,626건" 카드.
  유효 63.4% / 근접 4.6%, 초록(유효)·빨강(무효) 막대, "내 사정률" 세로 점선.
  사정률 칸에 `100.5` 입력 → **계산 없이** 79.0% / 4.1% 로 바뀌고 "위 투찰가는 100.15% 기준 — 계산하기를 다시 눌러야 갱신된다" 표시.
  다시 계산하기 → 투찰가·산식 문구가 100.50% 로, stale 문구 사라짐.
- 발주처를 "국군재정관리단" 으로 바꾸면 `law: national`, 3,350건, 100.15% 유효 57.6%.

## 알려진 미해결 사항
- 근접률 정의(c 바로 아래 0.10%p)는 bidding.py 의 c 스윕 표와 같은 기준이지만 "낙찰" 과는 다르다 —
  낙찰은 경쟁자 분포 문제라 분포 화면(/)의 영역이다. 이 카드는 유효/무효와 하한선 거리만 말한다.
- 히스토그램 조회는 요청마다 DB 를 읽는다 (16k 행, 51ms). 캐시 안 넣었다 — 계산 화면은 호출 빈도가 낮다.
- 브라우저 pane 스크린샷이 불안정해 그래프는 DOM(막대 180개, 세로선 1개, 눈금 97.7~102.1%)으로만 확인했다.
