# Handoff — T-036 추천 조준을 발주처 기준으로 고정 — 2026-09-20

## 변경한 파일
- `frontend/src/lib/distribution.ts` — `findBestAim()` 추가. 0.1%p 격자에서 발주처 σ 기준
  기대 낙찰(무효 반영)이 최대인 조준을 고른다. 동률이면 높은 조준, σ 없으면 null.
- `frontend/src/lib/distribution.test.ts` — `findBestAim` 테스트 6건.
- `frontend/src/pages/BidDistribution.tsx` — 추천 투찰가 카드가 `bestAim` 을 우선 쓰고,
  교환표의 추천 행(첫 행)도 같은 자리에 앵커. σ 없으면 기존 `bestBin` 으로 폴백.
  추천 근거 문구를 "발주처 σ 착지 분포 위 기대 낙찰 최대" 로 바꿈.
- `frontend/src/pages/BidDistribution.test.tsx` — σ 있을 때 카드·교환표가 같은 자리인지 확인.
- `tasks.md` — T-036 등록(done). 자사 투찰 85건 대조 결과와 project_id 충돌 버그 기록.

## Eval 에이전트가 확인해야 할 포인트
- `POST /api/v1/bid/distribution` 응답의 `preprice_sd_pct` > 0 인 공고(국방부·지자체 대부분)에서
  분포 페이지 추천 투찰가 카드에 "이 발주처 기준 조준 — 기대 낙찰 x%, 무효 확률 y%" 줄이 보이고,
  배지 offset 이 **+0.1%** 인지 (전역 히스토그램 기준 국가·지방 모두 +0.1).
- 교환표 "조준 위치 비교" 의 첫 행(추천)이 카드와 같은 offset·금액인지.
- 발주처 계약법 불명(`preprice_sd_pct` 0)인 공고는 예전처럼 "과거 낙찰 최빈 칸" 추천으로 나오는지.
- `cd frontend && npx vitest run && npx tsc --noEmit` — 157 passed, 타입 오류 없음.

## 알려진 미해결 사항
- **project_id 연도 충돌**: 국방부형 공고번호(`XXX0000-1`)가 해마다 재사용돼 `bids_history` /
  `bid_participants` 에서 다른 공고끼리 섞인다 (자사 85건 중 18건, 영향권 1,649건).
  발주처=국방부 스코프 분포는 이 버그가 고쳐질 때까지 신뢰하지 말 것.
- 고정 조준은 등수 산포를 줄일 뿐 1위를 만들지 않는다 — 같은 85건 반사실에서 어느 조준도 1위 0건.
