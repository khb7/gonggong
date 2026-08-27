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

### T-022 — A값을 낙찰자 투찰율에서 정확히 역산 (후보표 추측 제거)
- **why:** 현재 A값 역산은 낙찰하한가에서 **후보표를 뒤져 법정 하한율을 추측**한 뒤 그 값으로 A를 구한다.
  후보 간격이 좁은 구간(`0.87495`/`0.87745` 간격 0.0025)에서는 A값이 예정가격의 2%만 넘어도
  한 칸 위로 오분류되고, 그만큼 A값이 과소 산출된다. 이게 낙찰자 불변식 위반 잔여분의 원인이다.

  **추측이 필요 없는 경로가 있다.** `bid_participants.bid_rate` 는 참여자 원본의 **조정 투찰율**이라
  A값이 이미 반영돼 있다:
  ```
  bid_rate = (낙찰가 − A) / (예정가격 − A)
    ⇒ A = (낙찰가 − bid_rate × 예정가격) / (1 − bid_rate)      ← 정확. 후보표 불필요
  그 A로   legal_limit_rate = (낙찰하한가 − A) / (예정가격 − A)  ← 규정값에 스냅됨
  ```
- **status:** done (2026-08-27)
- **변경:**
  - `app/engine/a_value.py` — `derive_a_value_from_bid_rate()` (추측 없는 A값 역산),
    `snap_legal_limit_rate()` (규정값 스냅, 근처가 아니면 None 으로 오염을 드러냄)
  - `scripts/backfill_limits_from_bid_rate.py` (신규) — dry-run 기본
- **결과:**

  | | 작업 전 | 작업 후 |
  |---|---|---|
  | 낙찰자 불변식 위반 | 1,178 (9.8%) | **261 (2.15%)** |
  | A값 / 기초금액 평균 | 4.39% | **4.93%** |
  | `legal_limit_rate` 고유값 | 16 | 16 |

  1,063건 정정. 전부 하한율 자체가 바뀐 행이다:
  `0.81995→0.81395` 290 / `0.87495→0.86745` 222 / `0.85995→0.85495` 152 / `0.86745→0.85995` 134
- **notes:**
  - **반올림 노이즈 갱신을 막는 게 중요했다.** 하한율이 그대로인 행의 a_value 차이는
    예정가격 대비 p99 = 0.0009% 로 순수 반올림이다. 필터 없이 돌리면 9,745건을
    의미 없이 덮어쓴다. `_MATERIAL_A_RATIO = 0.001` 로 걸렀다.
  - `has_a_value` 는 태그 기반 값을 역산 실패(0)로 되돌리지 않게 OR 처리했다.
  - **잔여 261건 중 229건(88%)은 원본에 낙찰하한가가 없다.** 이 경로로는 풀 수 없고,
    T-010 이 다루는 문제와 같다. 나머지 32건은 스냅/불변식 안전장치가 거부한 행이다.
- **notes:**
  - **원본 파일이 필요 없다.** `bid_participants.bid_rate` 4.6M행이 이미 DB에 있으므로 백필로 처리된다.
    (참여자 원본 xls 는 구글드라이브에 539개만 남아 재파싱 불가 — T-017 참조)
  - 원본 정합성은 확인됐다: 낙찰하한가 ≤ 낙찰자 투찰금액이 940/949 성립(위배 9건).
    즉 소스가 아니라 우리 역산이 틀렸다.
  - `bid_rate ≠ (낙찰가−A)/(예정가−A)` 인 행이 1,841건인데 **전부 `a_value=0`** 이다.
    A값이 있는데 못 잡은 행들이고, 이 방식이면 잡힌다.

### T-010 — 낙찰자 불변식 위반 잔여 65건 처리
- **why:** `etl_participants.py --update-limits` 로 66.6% → 18.0% 까지 줄였으나 65건이 남았다.
  전부 원본에 낙찰하한가가 없어 갱신하지 못했고, 24건은 여전히 `0.87745` 하드코딩 값이다.
  `validate_data.py` 가 이 때문에 FAIL 한다 (의도된 동작).
- **status:** pending
- **acceptance:**
  - `validate_data.py` 의 `[불변식] 낙찰자 투찰율 < 법정 하한율` 이 0%
- **notes:** G2B API `sucsfLwstlmtRt` 로 보완할지, 해당 공고를 통계에서 제외할지 결정 필요.

### T-015 — 자사 낙찰률과 시장 기대치의 6~8배 격차 규명
- **why:** 깨끗한 표본 12,049건에서 `E[1/N] = 2.510%`. 전 공고에 투찰하는 평범한 업체의 기대 낙찰률이다. 현재 자사 낙찰률 0.3~0.4% 는 이보다 6~8배 낮다. 공고 선택으로 설명되는 폭은 1.37%(3억~50억)~3.26%(≤1억)로 2.4배뿐이라, 나머지 격차는 다른 원인이다.
- **status:** done (2026-08-27) — **원인 규명 완료. 분산(variance) 문제였다.**
- **자료:** `data/downloads/인포나의투찰성향*.xlsx` 11개 (Info21c `/mybox/myres` 전 10페이지, **151건**, 2026-05-27~08-27)
- **분석:** `python scripts/analyze_my_bids.py`
- **결론 — 편향과 분산 둘 다 문제다:**
  - **계통 편향 있음.** 오차 평균 **+0.2927%p** (SE 0.077, **t=3.79**). 실제 사정률보다 일관되게 낮게 본다.
  - **분산도 문제.** 잔차 sd **0.950%p** vs 실제 사정률 자체의 sd **0.630%p**(DB 전체 0.729%p).
  - 합산 RMSE **0.994%p** vs 고정값 방식 **0.630%p** → **예측이 무예측보다 1.58배 나쁘다.**
  - 예측력 상관 **r = +0.093 (p=0.255, n=151)** — 0과 구분 불가. 예측이 정보를 담고 있지 않다.
  - 151건 중 **101건(67%)이 하한 미달로 무효.** 편향 때문이다.
  - 낙찰자는 낙찰하한가 위 **+0.0014%**(중앙), 최대 +0.16%. 1억이면 1,400원.
  - 대형 편중(a)·적격심사 탈락(c) 아니다. 유효 50건 중 **최고 2위**까지 갔다 — 자리에 들어가면 붙는다.
- **⚠️ n=15 중간 분석의 두 결론은 소표본 착시였다:** ①"편향 없음(+0.005)" → 실제로는 +0.29%p 유의,
  ②"상관 r=−0.395(음의 예측력)" → n=151 에서 +0.093, 즉 무정보. 소표본 결론을 인용하지 말 것.
- **notes:** `1/E[N]`(0.258%)과 `E[1/N]`(2.510%)은 10배 차이 난다. 참여자 수 분포가 극단적으로 왜곡돼 있어(p5=10, p50=108, p95=1,397) 산술평균 기반 기준선은 쓰면 안 된다.
  **이 결과는 CLAUDE.md 의 "사정률 예측 폐기" 결정을 자사 실측으로 재확인한 것이다.**

### T-021 — `/bid/calculate` 응답 조립에서 500 (하한율 None + override)
- **why:** `app/api/v1/bidding.py:202` 의 `lower_limit_rate=float(notice.lower_limit_rate)` 가
  **원본 fetch 값**을 그대로 float() 한다. G2B 가 하한율을 못 주면(흔한 경우 — 그래서 400 안내 문구가 따로 있다)
  `None` 이라 `TypeError` 로 500 이 난다. override 로 하한율을 넣어 정상 계산이 끝난 뒤 응답 조립에서 죽는다.
  **override 가 이 상황의 정식 우회 경로인데 그 경로가 막혀 있다.**
- **status:** done (2026-08-27)
- **재현 (수정 전):**
  ```
  POST /api/v1/bid/calculate
  {"bid_notice_id":"TEST-001","overrides":{"base_price":1000000000,"lower_limit_rate":0.87745}}
  → 500 TypeError: float() argument must be ... not 'NoneType'
  ```
- **acceptance:** 위 요청이 200 을 반환하고 `fetched.lower_limit_rate` 는 `null` 로 나온다 ✅
- **변경:**
  - `app/schemas/response.py` — `FetchedData.lower_limit_rate: float | None`.
    상수로 채우지 않고 null 로 드러낸다 (`G2BNoticeData` 와 같은 규약).
  - `app/api/v1/bidding.py:202` — None 가드 후 변환.
  - `tests/test_api_bidding.py::test_calculate_survives_null_lower_limit_from_g2b` 추가.
- **notes:** 근본 원인은 **가드와 사용처가 다른 값을 본 것**이다. None 가드는 override 적용 *후*
  값에 걸려 있는데, 응답의 `fetched` 는 *원본* fetch 값을 싣는다. 그래서 override 로 계산이
  성공한 경우에만 터진다. `distribution.py` 는 같은 패턴이지만 149줄이 **해결된** 값을 쓰고
  93줄에서 이미 막아서 안전하다 — 확인함.
  테스트가 전부 하한율 있는 mock 을 써서 202건이 통과하면서도 안 잡혔다.

### T-020 — 발주처별 사정률 중심값 조회 (예측 아님)
- **why:** T-015 에서 자사 사정률 예측이 무예측보다 1.58배 나쁜 것이 151건으로 확인됐다.
  예측을 끄고 고정 사정률로 투찰하면 **하한가 근접 빈도가 3.8배**가 된다 (반사실, n=151):

  | 방식 | 유효% | 오차<0.05%p | **<0.10%p** | <0.20%p |
  |---|---|---|---|---|
  | 현재 (자사 예측) | 67% | 2 | **5** | 12 |
  | 전역 고정 c=100.05 | 55% | 7 | **19** | 33 |
  | 발주처별 평균 (LOO) | 55% | 9 | 16 | 30 |

- **status:** pending
- **acceptance:**
  - `bids_history.preprice_rate` 로 발주처별 사정률 중앙값·산포를 조회하는 경로
  - 화면에 "예측값"이 아니라 **분포 중심과 폭**으로 제시 (점 예측 금지)
  - 표본 부족 발주처는 지역 → 전체로 폴백
- **notes:**
  - **무효율을 낮추는 것이 목표가 아니다.** c 스윕상 c=99.30 이면 유효율 93% 지만 <0.10%p 적중은 11건으로
    떨어진다. 최적 c=100.05 의 유효율은 55% 다. 하한선 근접 밀도가 목표고 절반쯤 무효는 감수해야 한다.
  - **현 표본으로는 전역 고정이 발주처별보다 낫다** (<0.10%p 19 vs 16). 발주처별 표본이 3~15건뿐이라
    LOO 가 불안정하다. 발주처별로 가려면 `bids_history` 의 시장 데이터를 써야 하고, 표본 충분한 발주처만 골라야 한다.
  - 발주처별 실제 사정률 sd 는 전부 시장 평균의 절반 수준이다 — 조달청 인천 0.321 / 국군재정관리단 0.365 /
    경기도교육청 용인 0.392 / 제11기동사단 0.449 vs **시장 전체 0.729**. 발주처축 자체는 유효하다.
  - 국군재정관리단(n=15)은 실제 평균이 **100.2874** 인데 자사가 계속 낮게 봐서 무효율 73% 다. 여기만 고쳐도 15건이 산다.

### T-016 — G2B 공고 단건 조회 API 교체 (엔진 차단 버그)
- **why:** 현재 fetcher 가 쓰는 `PubDataOpnStdService`(개방표준 데이터셋)는 날짜범위 배치 조회용이라 `bidNtceNo` 단건 필터가 무시된다. 어떤 공고번호를 넣어도 데이터셋 첫 공고만 반환 → `/bid/distribution` 이 항상 동일한 잘못된 결과(base_price=0, region=unknown). 엔진 전체 무력화.
- **status:** pending
- **blocker (사용자 액션):** T-009 와 같은 활용신청 건이다. `입찰공고정보서비스(BidPublicInfoService)` 승인 전까지 진행 불가.
- **acceptance:**
  - fetcher 를 단건 조회(`inqryDiv=2` + `bidNtceNo`)로 재작성, 서로 다른 공고번호 → 서로 다른 정확한 공고 반환
  - 기초금액(bssAmt)/하한율은 ScsbidInfoService 단건 조회 또는 override 로 확보
- **notes:** 공고 데이터셋엔 presmptPrce 만 있고 bssAmt 가 없다(낙찰 데이터셋에만 존재, 개찰 후 공개). 투찰 시점엔 기초금액 미공개라 base_price=0 + override 가 도메인상 정상.

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

### T-017 — ETL 이 버리는 원본 컬럼 적재 (공고명 태그 / 사정률 / 원값)
- **status:** done (2026-08-26)
- **notes:** `bid_tags` 44,817행 적재, `bids_history.preprice_rate` 실측 mean 0.999162 / sd 0.007059,
  `bid_participants.base_rate`·`vs_lower_limit` 4,559,770 / 4,580,160행 채움. 재다운로드 없이 기존 xlsx 재적재만으로 끝냈다.
  `[시담]` 424 → 11건, `[현필]` 545 → 36건으로 줄어든 것은 정상이다 — 드롭된 행은 기초금액=0 인
  민간 발주 업체선정 공고(재건축조합·학교법인 등)로 예정가격 체계 자체가 없다. 공공 표본만 보면 `[현필]` 평균 21.8개사.

### T-018 — get_avg_participants() strict filter 로 인한 estimated_participants 저평가
- **status:** done (2026-08-25)
- **notes:** 완화 필터를 `get_avg_participants()` 에도 적용해 region 레벨 4 → 578. 수정 중 별개 버그를
  하나 더 찾아 같이 고쳤다 — `_avg()` 가 공종 조건을 쓰지 않는 발주처·지역 레벨에서도 `BidLicenseType` 을
  join 해서, 공고 하나에 붙은 공종 수(실 DB 최대 14개)만큼 중복 계산되고 있었다.

### T-019 — bid_participants.bid_rate 이상치로 인한 offset_pct 폭주
- **status:** done (2026-08-25) — **조회 시점 방어만 했다**
- **notes:** 조회 시 `0.5 <= bid_rate <= 1.05` 로 걸러 offset_pct 범위가 `-178%~+1729%` → `-34.7%~+14.9%`,
  구간 230 → 182 로 줄었다. 실측 이상치(4,637,505행 기준): `<= 0` 232행(rank 음수 파싱),
  `> 1.05` 2,271행(`bid_amount=99999999999999` 더미), `0~0.5` 1,916행(금액 자리수 깨짐).
  **ETL 이 계속 이상치를 넣고 있으므로 근본 수정은 남아 있다** — `scripts/etl_participants.py` 의심.

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
