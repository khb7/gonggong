# Info21c 자동화 구현 계획

작성일: 2026-03-28

---

## 목표

Info21c(인포21c)에서 공사낙찰 데이터를 자동으로 다운로드하여 `bids_history` DB에 적재.
현재 수동으로 사이트에서 CSV 내보내기 → DB 적재를 수동 반복하는 것을 완전 자동화.

---

## 현재 상태

| 항목 | 상태 | 설명 |
|------|------|------|
| Playwright 다운로더 | 🔵 구현됨 (셀렉터 검증 필요) | `scripts/info21c_downloader.py` |
| 클린 CSV ETL | ✅ 구현됨 | `scripts/etl_csv.py` (리팩터링 완료) |
| DB 적재 | ✅ 동작 | etl_csv.py에서 중복 체크 + upsert |
| 셀렉터 검증 | ⏳ 미완 | 실제 브라우저에서 필터 폼 확인 필요 |
| 스케줄링 | ⏳ 미구현 | 주 1회 자동 실행 |

---

## 즉시 해야 할 작업

### Step 1. Playwright 설치 및 첫 실행 테스트

```bash
pip install playwright
playwright install chromium

# --debug 모드로 실행 (브라우저 열어서 각 단계 확인)
python scripts/info21c_downloader.py --start 20260101 --end 20260131 --debug --type 0002
```

`--debug` 모드는:
- 각 단계에서 Enter를 눌러야 진행
- 자동화가 실패한 단계에서 수동으로 작업할 수 있음
- 셀렉터 확인에 활용

### Step 2. 셀렉터 검증 및 수정

`info21c_downloader.py`에서 검증이 필요한 부분:

| 위치 | 함수 | 확인 항목 |
|------|------|-----------|
| L54~70 | `login()` | ID/PW 입력 필드 selector |
| L87~97 | `set_search_filters()` | 날짜 입력 필드 selector |
| L101~118 | `set_search_filters()` | 낙찰방법 체크박스 selector |
| L120~131 | `set_search_filters()` | 면허업종 입력 selector |
| L148~155 | `set_search_filters()` | 조회 버튼 selector |
| L165~196 | `export_csv()` | 내보내기 버튼 및 다이얼로그 selector |

**셀렉터 찾는 방법:**
1. 브라우저에서 Info21c 접속
2. F12 (개발자 도구) → Elements 탭
3. 문제가 되는 요소 클릭 → id/name/class 확인
4. `info21c_downloader.py`의 해당 `for sel in [...]` 리스트에 추가

### Step 3. 내보내기 옵션 확인

내보내기 다이얼로그에서 설정해야 할 옵션:

| 옵션 | 설정값 | 이유 |
|------|--------|------|
| 파일 형식 | CSV | ETL 파서가 CSV 처리 |
| 구분자 | `,` (쉼표) | 표준 CSV |
| 리포트 제목 내보내기 | **OFF** | ON이면 헤더 앞에 메타데이터 행 추가됨 |
| 필터 세부사항 내보내기 | **OFF** | ON이면 검색 조건 수십 행이 추가됨 |
| 추가 열 제거 | **ON** | 선택하지 않은 컬럼 제거 |

### Step 4. 기대 CSV 컬럼 확인

다운로드 후 파일을 열었을 때 **첫 행이 바로 헤더**여야 합니다:

```
입찰공고번호,개찰순위,면허업종제한목록,낙찰하한율,투찰율,낙찰자선정여부,투찰일자,낙찰방법,수요기관,수요기관지역,수요기관사업자등록번호,기초금액,예산가격,투찰금액,입찰참여자수
```

`etl_csv.py`가 필요로 하는 최소 컬럼:
- `입찰공고번호`, `개찰순위`, `면허업종제한목록`
- `낙찰하한율`, `기초금액`, `예산가격`, `투찰금액`, `입찰참여자수`

있으면 더 좋은 컬럼 (없어도 동작):
- `투찰일자` → `bid_date`
- `낙찰방법` → `bid_type`
- `수요기관` → `client_name`
- `수요기관지역` → `region`
- `수요기관사업자등록번호` → `client_id`

---

## 전체 파이프라인

```
[수동/스케줄] python scripts/info21c_downloader.py --start YYYYMMDD --end YYYYMMDD
  → data/downloads/info21c_0002_YYYYMMDD_YYYYMMDD.csv
  → data/downloads/info21c_0023_YYYYMMDD_YYYYMMDD.csv
  ↓
python scripts/etl_csv.py --file data/downloads/info21c_0002_...csv
python scripts/etl_csv.py --file data/downloads/info21c_0023_...csv
  → bids_history 테이블에 적재
  ↓
POST /api/v1/bid/calculate
  → fallback_level: "none" → "client" / "region" 으로 전환됨
```

---

## 향후 작업 (우선순위 순)

1. **셀렉터 검증** — --debug 모드로 실행 후 실패 지점의 selector 확인 및 수정
2. **과거 데이터 일괄 수집** — 2023~2025년 3년치 백필
   ```bash
   # 연도별로 나눠서 실행 (Info21c 최대 조회 기간 확인 필요)
   python scripts/info21c_downloader.py --start 20230101 --end 20231231
   python scripts/info21c_downloader.py --start 20240101 --end 20241231
   python scripts/info21c_downloader.py --start 20250101 --end 20251231
   ```
3. **자동화 파이프라인** — 다운로드 + ETL을 하나의 스크립트로 연결
   ```bash
   python scripts/info21c_downloader.py --start ... --end ... | xargs python scripts/etl_csv.py --file
   ```
4. **Windows 작업 스케줄러** — 주 1회 자동 실행 설정
5. **fallback 수준 확인** — 3개월치 이상 쌓이면 "none" → "region"/"client" 전환 여부 확인

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `로그인 실패` | 동시 접속 제한 (오전에 다른 사람이 접속 중) | 오후/야간에 실행 |
| `내보내기 버튼 못 찾음` | selector 불일치 | `--debug` 모드로 F12 확인 |
| `필수 컬럼 누락` | 내보내기 시 컬럼 미선택 | 가이드 컬럼 선택 재확인 |
| 사정률 0.95 미만/초과 | `예산가격` 아닌 다른 컬럼 사용됨 | `예산가격` = 예정가격임을 확인 |
| 인코딩 오류 | 내보내기 옵션에서 인코딩 미선택 | UTF-8 또는 EUC-KR 확인 |

---

## 파일 구조

```
scripts/
├── info21c_downloader.py    ← Playwright 자동 다운로드 (신규)
├── etl_csv.py               ← 클린 CSV → DB 적재 (리팩터링)
├── backfill.py              ← G2B API 백필 (기존)
└── daily_collect.py         ← G2B API 일별 수집 (기존)

data/
└── downloads/               ← 다운로드된 CSV 저장 위치 (자동 생성)
```
