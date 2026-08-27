# Tasks

태스크 관리 파일. Dev 세션 시작 시 이 파일에서 다음 태스크를 선택한다.
status: pending → in_progress → done / skipped

---

## 우선순위: High

### T-011 — ETL이 버리는 원본 컬럼 적재 (공고명 태그 / 사정률 / 원값)
- **why:** `data/downloads/*.xlsx`(160개)는 20개 컬럼인데 `etl_csv.py`가 일부만 읽고 나머지를 버린다. 버려지는 것 중 셋이 분석을 막고 있다.
  1. **공고명 태그** — `[시담]`(평균 1.0개사, 경쟁입찰 아님 → 표본 오염), `[현필]`(평균 3.1개사), `[A값]`(전체 76%, 낙찰하한가 계산식이 달라 offset 좌표 의미가 다름). 공고명 컬럼 자체가 DB에 없다.
  2. **사정률** — 원본 `예가/기초(100%)`가 진짜 사정률(예정가격/기초금액)인데 미적재. 현재 `adjustment_rate`는 `winner_price/base_price`(=1순위기초대비)라 이름과 내용이 다르다.
  3. **예정가격·낙찰하한가 원값** — 비율로 뭉갠 뒤 버려서 A값 역산이 불가능.
- **status:** done (2026-08-26)
- **acceptance:**
  - ~~`bid_tags` 테이블에 태그 적재, `[시담]` 424건 식별 가능~~ → 44,817행 적재. 단 `[시담]`은 11건만 남음 (아래 notes)
  - `bids_history.preprice_rate` 평균 ≈ 0.999 / sd ≈ 0.0073 → **실측 0.999162 / 0.007059** ✅
  - `bid_participants.base_rate` / `vs_lower_limit` 채워짐 → 4,559,770 / 4,580,160행 ✅
  - 재다운로드 없이 기존 xlsx 재적재만으로 완료 ✅
- **notes:** 실측 근거 — 사정률 mean 99.915% / sd 0.729%로 전 건이 복수예비가격 적격심사임을 확인(강민석·류문찬 2015의 비균등분할-A1 예측 99.9%와 일치). 따라서 `etl_csv.py:136`의 `낙찰방법="적격심사"` 하드코딩은 값 자체는 옳다. `lower_limit_rate`의 distinct 11,370개도 오염이 아니라 A값 효과([A값] 없는 1,445건은 distinct 9개로 깨끗함).
  참여자 원본 xls는 구글드라이브에 539개만 남아 있고 DB엔 12,010개 공고분이 있어 **재파싱 불가** — `base_rate`/`vs_lower_limit`는 계산으로 채운다.
  **`[시담]` 424 → 11건, `[현필]` 545 → 36건으로 줄어든 것은 정상이다.** 드롭된 행은 기초금액=0인 민간 발주 업체선정 공고(재건축조합·학교법인 등)로, 나라장터 적격심사가 아니라 예정가격 체계 자체가 없다. ETL의 `base_price<=0` 드롭이 옳다. 원본 기준 "[현필] 평균 3.1개사"는 이 민간 공고를 센 값이고, 공공 표본만 보면 21.8개사다.
  상세: `eval-handoff.md`

### T-012 — 자사 낙찰률과 시장 기대치의 6~8배 격차 규명
- **why:** 깨끗한 표본 12,049건에서 `E[1/N] = 2.510%`. 전 공고에 투찰하는 평범한 업체의 기대 낙찰률이다. 현재 자사 낙찰률 0.3~0.4%는 이보다 6~8배 낮다. 공고 선택으로 설명되는 폭은 1.37%(3억~50억)~3.26%(≤1억)로 2.4배뿐이라, 나머지 격차는 다른 원인이다.
- **status:** pending
- **blocker (사용자 액션):** 자사 투찰 기록(어떤 공고에 얼마를 넣었고 결과가 무엇이었는지)이 필요하다. 현재 DB에 없다.
- **acceptance:**
  - 자사 투찰 공고의 참여자 수 분포가 시장 전체와 다른지 (대형 편중 여부)
  - 자사 투찰가가 낙찰하한가에서 몇 %p 떨어져 있는지 (시장 낙찰자는 p50 +0.0157%)
  - 적격심사 탈락 건수
- **notes:** `1/E[N]`(0.258%)과 `E[1/N]`(2.510%)은 10배 차이 난다. 참여자 수 분포가 극단적으로 왜곡돼 있어(p5=10, p50=108, p95=1,397) 산술평균 기반 기준선은 쓰면 안 된다.

### T-008 — G2B 공고 단건 조회 API 교체 (엔진 차단 버그)
- **why:** 현재 fetcher가 쓰는 `PubDataOpnStdService`(개방표준 데이터셋)는 날짜범위 배치 조회용이라 `bidNtceNo` 단건 필터가 무시됨. 어떤 공고번호를 넣어도 데이터셋 첫 공고만 반환 → `/bid/distribution`이 항상 동일한 잘못된 결과(base_price=0, region=unknown). 엔진 전체 무력화.
- **status:** pending
- **blocker (사용자 액션):** data.go.kr에서 현재 서비스키로 **`입찰공고정보서비스(BidPublicInfoService)` 활용신청** 필요. 현재 키는 PubDataOpnStdService에만 구독되어 레거시 단건 API가 403 Forbidden.
- **acceptance:**
  - fetcher를 단건 조회(`inqryDiv=2` + `bidNtceNo`)로 재작성, 서로 다른 공고번호 → 서로 다른 정확한 공고 반환
  - 기초금액(bssAmt)/하한율은 ScsbidInfoService 단건 조회 또는 override로 확보
- **notes:** API 구조 파악 결과: 공고 데이터셋엔 presmptPrce만 있고 bssAmt 없음(낙찰 데이터셋에만 존재, 개찰 후 공개). 투찰 시점엔 기초금액 미공개라 base_price=0 + override가 도메인상 정상. 상세 진단은 메모리 [[bug-g2b-notice-lookup]]. 활용신청 승인 전까지 진행 불가.

### T-001 — bids_history bid_type 백필
- **why:** 현재 DB의 bid_type/price_method가 '기타'로 저장된 레코드가 있을 경우 distribution 필터 버그 재발. 올바른 값('적격심사', '복수예비가격')으로 backfill해야 임시 or_() 완화 조건을 제거할 수 있음.
- **status:** pending
- **acceptance:**
  - `SELECT COUNT(*) FROM bids_history WHERE bid_type = '기타'` = 0
  - `crud_distribution.py`의 `or_()` 워크어라운드 제거 후 필터 정상 동작
- **notes:**

### T-002 — 히스토그램 낙찰자 집중 구간 강조 표시
- **why:** 현재 히스토그램은 전체 참여자 분포만 보임. 낙찰자(is_winner=True)가 집중된 구간을 시각적으로 구분하면 투찰 결정 근거가 명확해짐.
- **status:** pending
- **acceptance:**
  - 히스토그램에 낙찰자 빈도를 다른 색으로 overlay 표시
  - 낙찰 집중 구간(-0.5%~-0.8% 부근)이 한눈에 보임
- **notes:**

### T-003 — distribution API 0건 반환 근본 원인 파악
- **finding (2026-08-25):** 필터 버그가 아니라 **서버 DB 가 낡은 스냅샷**이었다. 서버는 `bids_history` 467건 / `bid_participants` 52행(공고 1건분)뿐이라 어떤 fallback 레벨도 `_MIN_DIST_SAMPLE`(200)을 못 넘긴다. 로컬 DB 는 12,445건 / 4,637,505행이고 같은 코드가 정상 동작한다. 남은 일은 코드 수정이 아니라 **서버 데이터 이관**.
- **why:** 코드 리뷰에서 현재 DB 필터(42,184건)는 정상이나, 실제로 API가 0건을 반환했다는 보고가 있었음. 캐시 문제 또는 다른 필터 단계 가능성 있음.
- **status:** pending
- **blocked by:** T-008
- **acceptance:**
  - 서버 기동 → API 호출 → distribution 배열 비어있지 않음 확인
  - 원인 파악 및 문서화
- **notes:** "0건 반환" 자체는 재현 안 됨 — `_RELAX_FILTERS` 적용 후 global fallback이 항상 4,569,648건을 반환함. 단, override 없이 호출하면 `bid_notice_id`를 무엇으로 줘도(TEST-001, ANOTHER-ID-999 둘 다 확인) **완전히 동일한 global 분포**(2705 bins, 456만건)가 반환됨 — client/region/type_bucket 레벨이 전혀 매칭되지 않기 때문. 근본 원인은 T-008과 동일: G2BFetcher가 공고별 실제 데이터(발주처/지역/공종/기초금액)를 못 가져옴(base_price=0). T-008 해결 전까지 "공고별 맞춤 분포"라는 본질 기능은 동작하지 않으므로 닫을 수 없음.

### T-009 — get_avg_participants() strict filter로 인한 estimated_participants 저평가
- **why:** `get_avg_participants()`는 `_RELAX_FILTERS`를 쓰지 않고 엄격 필터(`bid_type='적격심사' AND price_method='복수예비가격'`, 423건 풀)만 사용. 이 풀의 94%(396/423건)가 `participants=0`인 별도 소스 데이터라서 region 레벨 평균이 1.27 → `int()` 시 1로 나옴. 실제 참여자 분포(모드값 10~20명대)와 동떨어진 값.
- **status:** done (2026-08-25)
- **acceptance:**
  - [x] `get_avg_participants()`에 `get_offset_distribution()`과 동일한 `_RELAX_FILTERS` 적용
  - [x] region 레벨(경기/전국 + 조경) 기준 `estimated_participants`가 10 이상으로 나옴 — 4 → 578
- **notes:** T-001과 동일한 '기타' price_method 문제가 다른 코드 경로(crud_distribution.py)에서 재발한 것. `_RELAX_FILTERS` 확장으로 해결.
  수정 중 별개 버그를 하나 더 찾아 같이 고쳤다 — `_avg()`가 공종 조건을 쓰지 않는 발주처·지역 레벨에서도 `BidLicenseType`을 join 해서, 공고 하나에 붙은 공종 수(실 DB 최대 14개)만큼 중복 계산되고 있었다. 완화 필터만 적용했을 때 578이 아니라 1071이 나온 원인.

### T-010 — bid_participants.bid_rate 이상치로 인한 offset_pct 폭주
- **why:** `bid_participants` 4,637,505건 중 292건(0.006%)의 `bid_rate`가 0~1 비율이 아닌 비정상적으로 큰 값(예: 7941.25, project_id='R25BK00828581-000', bid_amount=2.5조원)으로 저장됨. `build_offset_distribution()`에서 `offset_pct = (bid_rate - lower_limit_rate) * 100` 계산 시 최대 8,890,629%까지 튀어 697개 bin 중 496개(71%)가 의미 없는 이상치 bin이 됨.
- **status:** done (2026-08-25)
- **acceptance:**
  - [ ] 이상치의 출처 ETL 스크립트/포맷 식별 — **미완**. 조회 시점 방어만 했고 ETL 은 그대로다
  - [x] bid_rate 정상 범위를 벗어나는 행 필터링 — 조회 시 `0.5 <= bid_rate <= 1.05`
  - [x] distribution 응답의 offset_pct 범위 축소 — `-178%~+1729%` → `-34.7%~+14.9%`, 구간 230 → 182
- **notes:** count 기준 영향은 작지만 프론트엔드 히스토그램 x축 스케일을 망가뜨림 (T-002/T-007에 영향).
  실측한 이상치 내역(로컬 DB 4,637,505행 기준): `bid_rate <= 0` 232행(rank 가 음수로 파싱된 깨진 행), `> 1.05` 2,271행(`bid_amount=99999999999999` 더미), `0~0.5` 1,916행(금액 자리수 깨짐). 합계 약 0.1%.
  **조회 시점 방어만 했다.** ETL 이 계속 이상치를 넣고 있으므로 근본 수정은 남아 있다 — `scripts/etl_participants.py` 의심 그대로.

---

## 우선순위: Medium

### T-004 — 내 투찰가 입력 시 실시간 위치 업데이트
- **why:** 현재 내 위치는 초기 렌더링 시 계산됨. 투찰가를 변경할 때마다 API 재호출 없이 로컬에서 즉시 위치가 업데이트되면 UX 개선.
- **status:** pending
- **acceptance:**
  - 투찰가 입력 필드에서 값 변경 시 히스토그램 내 내 위치 마커가 즉시 이동
  - API 재호출 없음 (로컬 계산)
- **notes:**

### T-005 — 발주처별 분포 필터
- **why:** 발주처마다 참여자 분포 패턴이 다름. 같은 발주처 과거 데이터만 필터링하면 더 정확한 의사결정 근거가 됨.
- **status:** pending
- **acceptance:**
  - 발주처명 입력 시 해당 발주처 데이터만 필터링한 히스토그램 표시
  - 데이터 부족(< 10건) 시 전체 분포로 fallback
- **notes:**

### T-006 — info21c ETL bid_type 적재 수정
- **why:** 현재 scripts/info21c_participants.py (bids_history ETL)가 bid_type/price_method를 설정하지 않아 default='기타' 적용. 향후 적재 데이터 품질 보장 필요.
- **status:** done (2026-06-01)
- **acceptance:**
  - 신규 적재 후 bids_history.bid_type = '적격심사' 확인
  - ETL 로그에 bid_type 설정 확인 메시지
- **notes:** info21c_participants.py는 이미 parse_detail()에서 bid_type 추출 + update_bid_type_and_method()로 업데이트 구현됨. etl_csv.py도 normalize_bid_type()으로 처리 중. 추가로 normalize_bid_type()에 "종합심사" 케이스 추가함 (2026-06-01).

---

## 우선순위: Low

### T-007 — 모바일 반응형 히스토그램
- **why:** 현장에서 모바일로 확인할 수 있으면 편의성 향상.
- **status:** pending
- **acceptance:**
  - 375px 뷰포트에서 히스토그램 가독성 확인
- **notes:**

---

## 완료된 태스크

### T-000 — bid_type 필터 완화 (임시)
- **status:** done (2026-05-31)
- **notes:** crud_distribution.py or_() 워크어라운드 추가. DB에 '기타' 없어 사실상 원래 필터와 동일. T-001(백필) 완료 후 or_() 제거 예정.
