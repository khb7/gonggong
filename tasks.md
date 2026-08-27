# Tasks

태스크 관리 파일. Dev 세션 시작 시 이 파일에서 다음 태스크를 선택한다.
status: pending → in_progress → done / skipped

최종 갱신: 2026-08-27

---

## 우선순위: High

### T-008 — A값 백필 적용 여부 결정
- **why:** 마이그레이션 `d5c7b39a4e10` 이 기존 18,409행의 legal/effective 를 둘 다
  `lower_limit_rate`(의미가 섞인 값)로 채워뒀다. `scripts/backfill_a_value.py` dry-run 결과
  11,568건이 갱신 대상이고 그 중 11,474건에서 A값이 발견된다. 추정 기반이라 미적용 상태로 뒀다.
- **status:** pending
- **acceptance:**
  - 적용하거나(`--apply`), 원본 엑셀 재적재(`etl_csv.py --upsert`)로 대체하거나, 보류를 결정하고 근거를 notes 에 기록
  - `validate_data.py` 의 낙찰자 불변식 위반이 악화되지 않을 것
- **notes:** 원본 엑셀이 있으면 재적재가 항상 더 정확하다. 백필은 원본이 없는 과거 적재분용.

### T-009 — 나라장터 입찰공고정보서비스 활용신청
- **why:** A값이 현재 수동 입력이다. G2B 개방표준 API 2개에는 A값 항목 자체가 없다.
  [15129394](https://www.data.go.kr/data/15129394/openapi.do) 는 기초금액정보·면허제한·지역제한을 제공하며,
  승인되면 A값 역산 대신 직접 수집이 가능해지고 T-011·지역제한 분리축도 같이 풀린다.
- **status:** pending
- **acceptance:**
  - 활용신청 승인 후 `getBidPblancListInfoCnstwkBsisAmount` 호출 성공
  - 응답에 A값 구성항목(안전관리비·국민연금·건강보험 등)이 오는지 확인하고 결과를 notes 에 기록
- **notes:** 현재 키는 미등록 — 호출 시 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(코드 30) 확인됨.
  코드 12(서비스 없음)가 아니므로 엔드포인트 경로는 유효하다.

### T-010 — 낙찰자 불변식 위반 잔여 65건 처리
- **why:** `etl_participants.py --update-limits` 로 66.6% → 18.0% 까지 줄였으나 65건이 남았다.
  전부 원본에 낙찰하한가가 없어 갱신하지 못했고, 24건은 여전히 `0.87745` 하드코딩 값이다.
  `validate_data.py` 가 이 때문에 FAIL 한다 (의도된 동작).
- **status:** pending
- **acceptance:**
  - `validate_data.py` 의 `[불변식] 낙찰자 투찰율 < 법정 하한율` 이 0%
- **notes:** G2B API `sucsfLwstlmtRt` 로 보완할지, 해당 공고를 통계에서 제외할지 결정 필요.

### T-001 — bids_history bid_type 백필
- **why:** bid_type/price_method 가 '기타'로 저장된 레코드가 있으면 distribution 필터 버그가 재발한다.
  올바른 값('적격심사', '복수예비가격')으로 백필해야 임시 `or_()` 완화 조건을 제거할 수 있다.
- **status:** pending
- **acceptance:**
  - `SELECT COUNT(*) FROM bids_history WHERE bid_type = '기타'` = 0
  - `crud_distribution.py` 의 `or_()` 워크어라운드 제거 후 필터 정상 동작
- **notes:** 진단상 현재 DB 에는 '기타'가 없어 완화 조건이 사실상 무해하다. 그래도 제거해야 재발을 막는다.

---

## 우선순위: Medium

### T-011 — `bid_participants.vs_lower_limit` 컬럼명 정정
- **why:** 컬럼명·주석이 "예비가격대비율 (낙찰하한율 기준 차이, %p)" 로 되어 있으나
  실제 내용은 원본 `업체별사정율(%)` 이다. 값 범위가 0.98~1.00 이라 낙찰자에 대해 `>= 0` 검사가
  무의미하게 통과한다. **이 컬럼으로 하한율을 역산하면 안 된다.**
- **status:** pending
- **acceptance:**
  - 컬럼명 마이그레이션 + 모델 주석 수정
  - 이 컬럼을 하한율 용도로 쓰는 코드가 없는지 확인
- **notes:** 근거: `md/design/bid_rate_definitions.md` 1절

### T-012 — 공고번호 조회 경로의 A값 힌트
- **why:** 붙여넣기 파싱은 A값을 자동 추출하지만, 공고번호만 입력하는 경로에서는
  `bids_history.has_a_value` 를 조회하지 않아 A값 안내가 없다.
- **status:** pending
- **acceptance:**
  - 공고번호 조회 시 A값 공고면 화면에 안내가 뜬다
- **notes:** T-008(백필) 이 먼저다. 지금 연동해도 대부분 `false` 로 나온다.

### T-014 — `select_center_offset` 의 safe / aggressive 가 같은 값이다
- **why:** 음수 offset 은 하한 미달 = 실격이라 `-MAD` 를 `+MAD` 로 정정했는데,
  그 결과 safe 와 aggressive 가 동일해졌다. 하한선 위로 얼마나 띄울지에 대한 전략 차이가 없다.
- **status:** pending
- **acceptance:**
  - 전략을 실제로 가르거나, 갈 필요가 없다면 함수를 단순화하고 그 판단을 문서화
- **notes:** `select_strategy()` 도 항상 "aggressive" 를 반환해 실사용 경로는 하나뿐이다.
  타점 선택이 분포 화면으로 옮겨가는 중이라 급하지 않다.

### T-007 — 모바일 반응형 히스토그램
- **why:** 현장에서 모바일로 확인할 수 있으면 편의성 향상.
- **status:** pending
- **acceptance:**
  - 375px 뷰포트에서 히스토그램 가독성 확인
- **notes:**

---

## 완료된 태스크

### T-013 — 폐기된 설계 문서에 배너 달기
- **status:** done (2026-08-27)
- **notes:** 5개 문서 상단에 배너를 달았다 — `md/reference/공공입찰.md`,
  `md/design/bidding_engine_design.md`, `md/plans/bidding-implementation-map.md`,
  `md/plans/implementation_plan.md`, `md/status/progress.md`(오래됨 경고).
  각 배너에 **그 문서에서 구체적으로 틀린 줄**과 대체 문서를 적었다.
  지우지 않고 남긴다 — 왜 그렇게 설계했었는지가 기록으로서 가치가 있다.

### T-002 — 히스토그램 낙찰자 집중 구간 강조 표시
- **status:** done (2026-08-27)
- **notes:** 낙찰자 빈도를 stacked bar 로 overlay 하고, `findWinZone()` 이 전체 낙찰의 60% 를 담는
  최소 폭 구간을 찾아 `ReferenceArea` 로 표시한다. 균등분포를 걸러내려고 폭 상한 대신
  집중도(담은 낙찰 비율 ÷ 차지한 폭 비율) 1.5배 기준을 쓴다.
  acceptance 에 적힌 "낙찰 집중 구간 -0.5%~-0.8%" 는 **하한율 오염 때문에 생긴 착시**였다.
  하한율 정정 후 실측 피크는 `+0.1% ~ +0.8%` 다 (하한 미달 구간은 애초에 실격이라 불가능).

### T-004 — 내 투찰가 입력 시 실시간 위치 업데이트
- **status:** done (2026-08-27)
- **notes:** `computeLocalPosition()` 을 `useMemo` 로 묶어 투찰가 입력 즉시 로컬 계산한다. API 재호출 없음.
  A값이 있으면 조정 투찰율 `(투찰금액−A)/(예정가격−A)` 기준으로 계산한다.

### T-005 — 발주처별 분포 필터
- **status:** done (2026-08-27)
- **notes:** `resolve_offset_distribution()` 이 발주처 → 지역 → 공종+버킷 → 전체 순으로 폴백한다.
  채택 기준은 참여자 행 수가 아니라 **공고 수 10건** — 공고 1건에 수백 명이 참여하므로
  행 수로 재면 한 건의 특수 상황이 "발주처 분포"로 둔갑한다.
  실제로 쓰인 레벨을 `data_quality` 로 응답에 실어 화면 배지로 드러낸다.

### T-003 — distribution API 0건 반환 근본 원인 파악
- **status:** done (2026-08-27)
- **notes:** 실제 호출로 정상 응답 확인 (level=client, 공고 40건, bin 103개).
  근본 원인은 필터가 아니라 **하한율 오염**이었다 — offset 기준선이 공고마다 제각각 밀려 있어
  히스토그램 모양 자체가 무의미했다. `md/design/bid_rate_definitions.md` 4절 참고.

### T-006 — info21c ETL bid_type 적재 수정
- **status:** done (2026-06-01)
- **notes:** `info21c_participants.py` 는 `parse_detail()` + `update_bid_type_and_method()` 로 이미 구현.
  `etl_csv.py` 도 `normalize_bid_type()` 으로 처리. "종합심사" 케이스 추가함.

### T-000 — bid_type 필터 완화 (임시)
- **status:** done (2026-05-31)
- **notes:** `crud_distribution.py` `or_()` 워크어라운드 추가. DB에 '기타' 없어 사실상 원래 필터와 동일.
  T-001(백필) 완료 후 제거 예정.
