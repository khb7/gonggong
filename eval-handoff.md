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

---

# Handoff — 용어 ⓘ 툴팁 (TermHint + glossary) — 2026-09-22

## 변경한 파일
- `frontend/src/lib/glossary.ts` — **신규**. 용어 사전 한 곳 (뜻 / 산식 / 왜). 14개 용어
- `frontend/src/components/TermHint.tsx` — **신규**. 라벨 옆 ⓘ 아이콘 + Radix Tooltip. 클릭 토글을 얹어 터치에서도 열린다. Provider 를 품어 어디서나 동작
- `frontend/src/pages/BidCalculator.tsx` — 기초금액·하한율·A값·사정률·사정률 산포·유효·근접·예정가격 대비 비율에 부착. `Input title=` 제거
- `frontend/src/pages/BidDistribution.tsx` — 기초금액·하한율·A값·기대 낙찰·무효 확률·내 offset·공격성·과거 낙찰 빈도·낙찰 집중 구간에 부착
- `frontend/src/components/TermHint.test.tsx` — 열기 전 숨김 / 클릭으로 열림·닫힘 / 사전 항목 완결성

## Eval 에이전트가 확인해야 할 포인트
- `/calculator`, `/` 두 화면에서 라벨 옆 ⓘ 에 마우스를 올리면 제목·정의·산식(monospace)·비고 순서로 뜬다. 클릭해도 열리고 다시 클릭하면 닫힌다.
- 두 화면의 같은 용어(기초금액·하한율·A값)가 같은 문구다.
- 정의가 제도와 맞는지: `md/reference/공공입찰_제도_가이드.md`, `md/design/bid_rate_definitions.md` 와 대조.

## 알려진 미해결 사항
- 툴팁은 스크롤하면 닫힌다 (Radix 기본). 긴 정의를 읽다 스크롤하면 사라진다 — 지금 길이(3줄)에서는 문제 안 됨.

---

# Handoff — 도감 페이지 (/reference) — 2026-09-22

## 변경한 파일
- `frontend/src/lib/glossary.ts` — 용어 14 → 24개 (추정가격·예정가격·복수예가·낙찰하한가·실효 하한율·투찰율·적격심사·개찰·Fallback·버킷 추가). `group`(price/rule/engine/data)·`where`(어디서 보이나) 필드 추가. 툴팁은 `where` 를 안 보이고 도감만 보인다
- `frontend/src/lib/reference.ts` — **신규**. 흐름 6단계, 하한율 개정표, 계약법 비교표, 논문 2편, 출처 링크 10개, 엔진 판단 8건
- `frontend/src/pages/Reference.tsx` — **신규**. 5섹션 + 앵커 목차. 서버 호출 없음
- `frontend/src/App.tsx`, `components/AppSidebar.tsx` — `/reference` 라우트 + 사이드바 "도감"
- `frontend/src/pages/Reference.test.tsx` — 섹션·용어 완결성·펼침·표·논문·링크(target/rel)·판단, 그리고 자료 무결성(https·중복·분류)

## Eval 에이전트가 확인해야 할 포인트
- `/reference`: 목차 5개 클릭 시 앵커 이동. 용어 행 클릭하면 뜻/산식/왜/어디서 보이나 펼쳐짐
- 논문 2편이 "문헌의 주장" vs "우리 데이터" 두 블록으로 나뉘고 배지가 각각 불일치(김도영 2020) / 재현됨(강민석·류문찬 2015)
- 출처 링크 10개가 새 탭(`target=_blank`, `rel=noopener`)
- 판단 8건 각각 근거 수치 목록 + 빨간 "하지 말아야 할 것" 박스 + 출처(T 번호/파일)
- 용어 툴팁(ⓘ)과 도감의 정의가 같은 문장인지 — 같은 `GLOSSARY` 를 읽으므로 구조상 어긋날 수 없다

## 알려진 미해결 사항
- 자사 투찰 실적(151건, RMSE, 낙찰률)이 공개 사이트에 그대로 노출된다 — 사용자 확인 후 의도적으로 넣었다
- 수치는 하드코딩이라 DB 가 갱신돼도 자동으로 안 바뀐다. 재분석 후에는 `reference.ts` 를 손으로 고쳐야 한다
