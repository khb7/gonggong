# 계획: Info21c 데이터 수집 실행 계획

**작성일:** 2026-03-30
**목적:** bids_history DB를 채워 엔진이 실제 예측을 할 수 있는 상태로 만들기
**기대 결과:** fallback_level `"default"` → `"client"` / `"region"` 으로 전환

---

## 현재 상태 요약

| 항목 | 상태 |
|------|------|
| `info21c_downloader.py` | 완전 구현됨. 셀렉터 검증만 남음 |
| `etl_csv.py` | 완전 구현됨. 즉시 사용 가능 |
| `bids_history` 테이블 | 비어 있음 (DB 마이그레이션은 됐는지 확인 필요) |
| Playwright | 설치 여부 확인 필요 |

스크립트 자체는 완성되어 있다. 실행 전 환경 확인 + 사이트 셀렉터 검증이 핵심이다.

---

## 전체 흐름

```
0. 사전 준비 (DB 확인 + Playwright 설치)
       ↓
1. --debug 모드로 시범 실행 (소구간: 1개월)
       ↓
2. 셀렉터 문제 있으면 수정 → 재실행
       ↓
3. CSV 다운로드 성공 확인
       ↓
4. etl_csv.py로 DB 적재
       ↓
5. 데이터 적재 결과 확인 (건수, 사정률 분포)
       ↓
6. 과거 3년치 백필
```

---

## Step 0. 사전 준비

### 0-1. DB 마이그레이션 상태 확인

```bash
alembic current
```

`head`가 아니면 먼저 마이그레이션 실행:
```bash
alembic upgrade head
```

bids_history 테이블 존재 확인:
```bash
# PostgreSQL 접속 후
\dt bids_history
SELECT COUNT(*) FROM bids_history;
```

### 0-2. Playwright 설치 확인

```bash
python -c "from playwright.async_api import async_playwright; print('OK')"
```

실패하면:
```bash
pip install playwright
playwright install chromium
```

### 0-3. Info21c 접속 가능 여부 확인

- 브라우저에서 직접 `https://www.info21c.net` 접속
- ID: `nw8856` / PW: `nw8856` 로그인 테스트
- **오전 9~18시는 다른 직원이 사용 중일 수 있음** → 오후 6시 이후 또는 주말에 실행 권장

---

## Step 1. 시범 실행 (--debug 모드, 소구간)

목적: 셀렉터 검증. 자동화 실패 지점 파악.

```bash
python scripts/info21c_downloader.py \
  --start 20260101 --end 20260228 \
  --type 0002 \
  --debug
```

`--debug` 모드에서 브라우저가 열리고 각 단계에서 Enter를 눌러야 진행된다.
각 단계별로 아래를 확인:

### 확인 포인트 1: 로그인

```
[1/4] 로그인 중...
  → 로그인 성공 (현재 URL: https://...)
```

실패 시:
- URL에 `login`이 남아 있으면 ID/PW 오류 또는 동시 접속 제한
- 필드를 못 찾으면: 브라우저 F12 → Elements → ID/PW 입력 필드의 `name` 속성 확인
  - 코드가 시도하는 셀렉터: `input[name='id']`, `#id`, `input[placeholder='아이디']`
  - 실제 값이 다르면 `info21c_downloader.py` L63, L72 배열에 추가

### 확인 포인트 2: 날짜 및 공종 필터

```
[2/4] 검색 조건 설정 중...
  → 날짜 설정: 2026-01-01 ~ 2026-02-28
  → 공종 선택: C081 (실내건축)
  → 검색 완료 (N건 로드됨)
```

실패 시:
- 날짜 필드: 코드가 사용하는 셀렉터는 `#config_from_date`, `#config_to_date`
- 공종 셀렉트: `#search_code1` (value: `C081`=실내건축, `C084`=조경)
- 조회 버튼: `#topSearchBtn`
- 위 셀렉터가 틀렸으면 F12 → Elements에서 실제 id 확인 후 `set_search_filters()` 수정

### 확인 포인트 3: 내보내기

```
[3/4] 엑셀 내보내기 중...
  → 저장 완료: data/downloads/info21c_0002_20260101_20260228.xlsx
```

**⚠ 중요 주의사항:** 내보내기 다이얼로그가 열리면 아래 옵션 반드시 확인:

| 옵션 | 올바른 설정 | 잘못 설정 시 증상 |
|------|------------|-----------------|
| 파일 형식 | **CSV** (Excel이 아닌 CSV) | xlsx로 내려오면 etl_csv.py 파싱 불가 |
| 구분자 | `,` (쉼표) | `\t` 등이면 컬럼 분리 실패 |
| 리포트 제목 내보내기 | **OFF** | 헤더 앞에 메타데이터 수십 행 추가됨 |
| 필터 세부사항 내보내기 | **OFF** | 검색 조건 행이 삽입됨 |
| 추가 열 제거 | **ON** | 선택 안 된 컬럼 제거 |

다이얼로그가 있으면 `--debug` 중 Enter 누르기 전에 직접 옵션 설정 후 다운로드 버튼 클릭.

---

## Step 2. 다운로드 파일 확인

다운로드 후 파일을 텍스트 에디터(또는 Excel)로 열어 확인:

### 확인 1: 첫 행이 바로 헤더인가

```
올바른 형태:
입찰공고번호,개찰순위,면허업종제한목록,낙찰하한율,...

잘못된 형태:
조회기간: 2026-01-01 ~ 2026-02-28   ← 이런 메타데이터 행이 있으면 안 됨
필터: 공종=실내건축
...
입찰공고번호,개찰순위,...
```

메타데이터 행이 있으면 `etl_csv.py`가 "필수 컬럼 누락" 오류를 낸다.
→ 내보내기 옵션에서 "리포트 제목"과 "필터 세부사항"을 OFF로 설정 후 재다운로드.

### 확인 2: 필수 컬럼이 있는가

etl_csv.py가 필요로 하는 컬럼 최소 목록:
```
입찰공고번호, 개찰순위, 면허업종제한목록, 낙찰하한율,
기초금액, 예산가격, 투찰금액, 입찰참여자수
```

없는 컬럼이 있으면 Info21c에서 컬럼 선택을 다시 해서 재다운로드.

### 확인 3: 파일이 CSV인가

- 확장자가 `.xlsx`이면 `etl_csv.py`가 처리 못 함
- 내보내기 시 **"일반텍스트 사용한 excel, csv"** 옵션 선택해야 CSV로 내려옴
- `.xlsx`로 내려왔다면 Excel에서 열어서 "다른 이름으로 저장 → CSV(쉼표로 분리)"로 변환 후 사용

---

## Step 3. ETL 실행

```bash
python scripts/etl_csv.py --file data/downloads/info21c_0002_20260101_20260228.csv
```

기대 출력:
```
1. 파일 읽는 중: ...
  → 인코딩: utf-8-sig, 행 수: 1234
  → 1순위(낙찰자) 행: 1234건
  → 드롭: 값 오류 N건, 공종 미매핑 N건, 파싱 오류 N건
  → DB 적재 대상: NNN건
2. DB 적재 중... (NNN건)
  → 신규 NNN건 적재 / 중복 0건 스킵

완료: 신규 NNN건 / 스킵 0건
```

### 드롭 건수가 너무 많을 때

`드롭: 값 오류 N건`이 전체의 30% 이상이면 원인 파악 필요:

| 원인 | 확인 방법 | 조치 |
|------|----------|------|
| 사정률 0.95~1.05 범위 밖 | 예산가격/기초금액 컬럼 확인 | 다른 컬럼이 예정가격으로 쓰인 경우 `etl_csv.py` L136 수정 |
| 기초금액 0 | CSV에서 해당 행 확인 | 데이터 자체 문제 → 허용 범위 |
| 공종 미매핑 대량 발생 | `면허업종제한목록` 컬럼값 직접 확인 | `0002`/`0023` 코드가 다른 형식이면 `normalize_project_type()` 수정 |

---

## Step 4. 적재 결과 검증

```sql
-- 적재 건수 확인
SELECT project_type, COUNT(*) as cnt
FROM bids_history
GROUP BY project_type;

-- 사정률 분포 확인 (이 범위를 벗어나면 이상 데이터)
SELECT
  project_type,
  MIN(adjustment_rate),
  MAX(adjustment_rate),
  AVG(adjustment_rate),
  COUNT(*)
FROM bids_history
GROUP BY project_type;

-- 발주처별 건수 Top 10
SELECT client_name, COUNT(*) as cnt
FROM bids_history
GROUP BY client_name
ORDER BY cnt DESC
LIMIT 10;
```

정상 범위:
- 사정률: 0.95 ~ 1.05 (코드에서 이미 필터링하지만 재확인)
- 발주처 데이터가 20건 이상인 기관이 있으면 fallback_level이 "client"로 전환됨

---

## Step 5. 과거 데이터 백필 계획

시범 실행이 성공하면 3년치 과거 데이터를 수집한다.

```bash
# 2023년 (실내건축)
python scripts/info21c_downloader.py --start 20230101 --end 20231231 --type 0002
python scripts/etl_csv.py --file data/downloads/info21c_0002_20230101_20231231.csv

# 2023년 (조경)
python scripts/info21c_downloader.py --start 20230101 --end 20231231 --type 0023
python scripts/etl_csv.py --file data/downloads/info21c_0023_20230101_20231231.csv

# 2024년
python scripts/info21c_downloader.py --start 20240101 --end 20241231 --type 0002
python scripts/etl_csv.py --file data/downloads/info21c_0002_20240101_20241231.csv

python scripts/info21c_downloader.py --start 20240101 --end 20241231 --type 0023
python scripts/etl_csv.py --file data/downloads/info21c_0023_20240101_20241231.csv

# 2025년
python scripts/info21c_downloader.py --start 20250101 --end 20251231 --type 0002
python scripts/etl_csv.py --file data/downloads/info21c_0002_20250101_20251231.csv

python scripts/info21c_downloader.py --start 20250101 --end 20251231 --type 0023
python scripts/etl_csv.py --file data/downloads/info21c_0023_20250101_20251231.csv
```

**Info21c 조회 기간 제한이 있을 수 있다.** 1년 단위 조회가 안 되면 분기별로 나눠서 실행:
```bash
# 분기별 예시
python scripts/info21c_downloader.py --start 20230101 --end 20230331 --type 0002
python scripts/info21c_downloader.py --start 20230401 --end 20230630 --type 0002
...
```

---

## 코드에서 발견된 잠재적 이슈

실행 전 인지하고 있어야 할 사항들.

### 이슈 1: 내보내기가 xlsx로 내려올 가능성

`export_csv()` 코드를 보면 다운로드 파일이 `.xlsx`로 올 경우를 처리하고 있다:
```python
suffix = Path(download.suggested_filename).suffix or ".xlsx"
output_path = output_stem.with_suffix(suffix)
```

그런데 `etl_csv.py`는 `pd.read_csv()`만 사용하므로 `.xlsx` 파일은 파싱 실패한다.
→ 반드시 내보내기 옵션에서 **CSV 형식** 을 명시적으로 선택해야 한다.

만약 사이트가 항상 xlsx로만 내보내기를 지원한다면 `etl_csv.py`에 xlsx 파싱 로직 추가가 필요하다.

### 이슈 2: 로그인 성공 판정 로직

```python
if "login" in page.url.lower() or "member" in page.url.lower():
    raise RuntimeError("로그인 실패")
```

로그인 성공 후 URL에 `member`가 포함될 수 있는 경우가 있으면 오탐 가능성이 있다.
로그인 후 실제 URL을 `--debug` 모드에서 직접 확인하고, 문제가 있으면 판정 조건을 수정한다.

### 이슈 3: 다이얼로그 없이 직접 다운로드 시 파일 미저장

```python
else:
    async with page.expect_download(timeout=60_000) as dl_info:
        pass  # 이미 클릭됨
```

엑셀 버튼 클릭 직후 `expect_download` 컨텍스트에 진입하는 구조인데,
이미 클릭이 완료된 시점에서 다운로드 이벤트를 잡지 못할 가능성이 있다.
→ 만약 이 경로에서 다운로드가 안 되면 클릭과 `expect_download`를 동시에 실행하는 방식으로 수정 필요.

---

## 체크리스트

실행 시작 전:
- [ ] `alembic upgrade head` 완료 확인
- [ ] PostgreSQL 접속 가능 확인 (`.env` `DATABASE_URL` 유효)
- [ ] Playwright + chromium 설치 완료
- [ ] Info21c 브라우저 수동 접속 가능 확인 (오전 피하기)

시범 실행 후:
- [ ] CSV 파일이 `data/downloads/`에 생성됨
- [ ] CSV 첫 행이 헤더 (메타데이터 행 없음)
- [ ] 필수 컬럼 8개 모두 존재
- [ ] 파일 형식이 `.csv` (`.xlsx` 아님)

ETL 후:
- [ ] `bids_history` 에 데이터 적재됨 (`SELECT COUNT(*) > 0`)
- [ ] 사정률 분포가 0.95~1.05 범위 내
- [ ] `fallback_level` 이 `"default"` 이외 값으로 나오는 발주처가 존재

---

## 성공 기준

3년치 백필 완료 시 기대 데이터 규모:
- 실내건축 + 조경 합산 약 수천 건 예상
- 단골 발주처 (국방부, 교육청, 경기도 지자체) 20건 이상 확보 → fallback_level `"client"` 전환
- confidence_grade `"high"` 발주처 최소 5개 이상 확보
