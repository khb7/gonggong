# Handoff — T-037 국방부형 공고번호 연도 충돌 수정 + T-036 고정 조준 — 2026-09-20

## 변경한 파일
- `app/etl/project_id.py` — 신규. `canonical_project_id()`: 국방부형 번호(`LPK0148-1`)에 개찰 연도를 붙인다 (`LPK0148-1@2026`). G2B 번호는 그대로.
- `scripts/etl_csv.py`, `app/etl/participant_excel.py`, `app/etl/info21c_notice.py`, `app/etl/info21c_final_awards.py` — 네 leg 모두 이 함수를 거친다.
- `scripts/info21c_participants.py` — Excel 을 먼저 읽어 개찰일시로 정규화한 뒤 bids_history 를 갱신한다.
- `app/db/crud.py` — `get_open_notice()` 가 연도 없는 입력을 최근 연도로 찾는다.
- `scripts/rekey_military_project_ids.py` — 신규. 기존 DB 재키잉 (dry-run 기본, `--apply`).
- `tests/test_project_id.py`, `tests/test_etl_csv.py`, `tests/test_final_awards.py` — 테스트 추가.
- `CLAUDE.md` — 하지 말아야 할 것에 규칙 추가. `tasks.md` — T-037 done.
- (T-036, 이전 커밋) `frontend/src/lib/distribution.ts` `findBestAim()`, `BidDistribution.tsx` 추천 카드.

## Eval 에이전트가 확인해야 할 포인트
- `POST /api/v1/bid/distribution` 에 `{"bid_notice_id": "LPK0148-1"}` (연도 없음) 을 넣으면 `bid_notices_open` 에 있을 때 `g2b_fetch_status == "info21c"` 로 잡히는지 (없으면 예전처럼 G2B 경로).
- 발주처=국방부 계열 공고의 분포 응답 `data_quality.distribution_level` 이 client 로 잡히고 히스토그램이 나오는지 (재키잉 전엔 두 해 참여자가 섞여 있었다).
- 분포 페이지 추천 투찰가 카드에 "이 발주처 기준 조준" 줄과 offset **+0.1%** 배지, 교환표 첫 행이 같은 금액인지.
- `pytest tests/` 315 passed, `cd frontend && npx vitest run && npx tsc --noEmit` 157 passed.
- `validate_data.py`: 불변식 위반 11/15,586 (0.07%), WARN 만 — FAIL 없음.

## 알려진 미해결 사항
- 고아 참여자 공고 254건 (목록 Excel 에 없는 공고). 이 중 90건은 재키잉으로 드러난 국방부형. 목록 leg 를 그 기간으로 다시 받으면 채워진다.
- bids_history 국방부형 33건은 bid_date 가 없어 원본 키로 남아 있다. 참여자는 붙지 않는다.
- 고정 조준은 등수 산포를 줄일 뿐 1위를 만들지 않는다 — 자사 85건 반사실에서 1위 0.
