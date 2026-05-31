# Tasks

태스크 관리 파일. Dev 세션 시작 시 이 파일에서 다음 태스크를 선택한다.
status: pending → in_progress → done / skipped

---

## 우선순위: High

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
- **why:** 코드 리뷰에서 현재 DB 필터(42,184건)는 정상이나, 실제로 API가 0건을 반환했다는 보고가 있었음. 캐시 문제 또는 다른 필터 단계 가능성 있음.
- **status:** pending
- **acceptance:**
  - 서버 기동 → API 호출 → distribution 배열 비어있지 않음 확인
  - 원인 파악 및 문서화
- **notes:** crud_distribution.py or_() 워크어라운드 추가 후 현재는 동작 가능성 있음. 먼저 실제 API 호출로 확인 필요.

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
