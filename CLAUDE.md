# CLAUDE.md — 공공입찰 통계 엔진

## 프로젝트 개요

나라장터(G2B) 공공입찰 데이터를 기반으로 **경쟁자 투찰 분포를 보여주는 의사결정 도구**.
실내건축·조경 공종을 주 대상으로 한다.

> ⚠️ **사정률 예측은 폐기됐다.** 사정률은 복수예비가격 구조상 다수 입찰자의
> 번호 선택 결과라 예측 대상이 아니다(avg≈1.0, std≈0.007).
> 현재 방향은 **과거 참여자 분포 위에 내 위치를 얹어 보여주는 것**이다.
> 근거: `md/design/2026-05-29-distribution-engine-analysis.md`

핵심 흐름 (주 경로):
```
POST /api/v1/bid/distribution
  → 공고 정보 (기초금액, 법정 하한율, A값, 발주처, 지역)
  → bid_participants 에서 과거 참여자 offset 분포 조회
     (발주처 → 지역 → 공종+버킷 → 전체 순 fallback, 채택 기준은 공고 수)
  → offset 히스토그램 + 낙찰 집중 구간 + 내 투찰가 위치
```

`POST /api/v1/bid/calculate` (사정률 기반 투찰가 계산)은 **동결 상태**로 유지된다.
신규 기능은 여기에 붙이지 않는다.

---

## 도메인 핵심 개념

| 용어 | 설명 |
|------|------|
| **기초금액** (base_price) | 발주처가 공개하는 예정가격 기준선 (원) |
| **예정가격** | 개찰 시 확정되는 실제 낙찰 기준가. 복수예비가격 15개 중 4개 평균 |
| **사정률** (adjustment_rate) | 예정가격 ÷ 기초금액. 제도가 만들어내는 난수에 가깝다 |
| **법정 낙찰하한율** (legal_limit_rate) | 예정가격 대비 투찰 가능한 최저 비율. **A값 제외 기준선** (2026 현행: 10억 미만 공사 0.89745) |
| **실효 낙찰하한율** (effective_limit_rate) | 낙찰하한가 ÷ 예정가격. A값이 녹아든 값 |
| **A값** (a_value) | 투찰율 적용에서 **제외**되는 법정경비 합계 (국민연금·건강보험·산업안전보건관리비 등 7항목) |
| **투찰율** (bid_rate) | `(투찰금액 − A) / (예정가격 − A)`. **원본이 이미 A값을 뺀 조정값이다** |
| **offset** | `투찰율 − 법정 하한율`. 분포 히스토그램의 x축 |
| **Fallback** | 발주처→지역→공종+버킷→전체 순 계층 조회. 채택 기준은 참여자 행 수가 아니라 **공고 수** |
| **버킷** (bucket_id) | 기초금액 구간 분류 (1: ~1억, 2: 1억~5억, 3: 5억~20억, 4: 20억+) |

### 낙찰하한가 산식 (반드시 A값 포함)

```
낙찰하한가 = (예정가격 − A값) × 법정하한율 + A값
투찰가     = (예정가격 − A값) × (법정하한율 + offset) + A값
```

A값을 빼먹고 `예정가격 × 하한율`로 계산하면 **하한가 미달로 부적격 탈락**한다.
실측상 건축공사 공고의 **70%가 A값 공고**다 (A값 비중 평균 3.71%).

### 하지 말아야 할 것

- **낙찰하한율에 기본값을 채우지 않는다.** 구간·계약법·개정시점마다 다른 값이라,
  모르면 `None` 으로 두고 실패시킨다. `0.87745` 하드코딩이 과거 데이터 오염의 근본 원인이었다.
- **offset 기준선은 법정 하한율이다.** 실효 하한율로 재면 A값이 이중 차감된다.

상세: `md/reference/공공입찰_제도_가이드.md`, `md/design/bid_rate_definitions.md`

---

## 디렉토리 구조

```
app/
├── api/v1/
│   ├── distribution.py     # POST /bid/distribution  ← 주 경로
│   ├── bidding.py          # POST /bid/calculate     ← 동결
│   ├── stats.py            # 관리 대시보드
│   └── admin.py            # CSV 업로드
├── core/config.py          # 환경변수 설정 (DATABASE_URL, G2B_API_KEY)
├── data/fallback.py        # (deprecated) 사정률 계층 fallback
├── db/
│   ├── models.py           # BidsHistory, BidParticipants, BidLicenseType, ...
│   ├── crud_distribution.py# 분포 조회 + fallback 스코프 + 캐시  ← 주 경로
│   ├── crud.py             # 읽기 전용 / crud_write.py 쓰기
│   ├── normalize.py        # 공종·지역·입찰방식 정규화
│   └── session.py          # AsyncSession, Base
├── engine/
│   ├── distribution.py     # offset 히스토그램, 내 위치 계산  ← 주 경로
│   ├── a_value.py          # A값 역산·실효 하한율·A값 반영 투찰가
│   ├── statistics.py       # trimmed_median(), mad()
│   ├── digit_filter.py     # 끝자리 블랙리스트 회피
│   ├── calculator.py       # (동결) 투찰가 계산
│   └── strategy.py         # (동결) select_strategy(), generate_bid_spread()
├── external/
│   ├── g2b_fetcher.py      # 단건 공고 조회 (Mock 포함)
│   └── g2b_collector.py    # 날짜 범위 일괄 수집
└── schemas/                # request / response / distribution

scripts/
├── etl_csv.py              # Info21c CSV·XLSX → bids_history (A값 역산 포함)
├── etl_participants.py     # 참여자 XLS → bid_participants (+ --update-limits)
├── backfill_a_value.py     # 과거 적재분 A값 역산 (dry-run 기본)
├── validate_data.py        # 적재 후 품질 검증 (낙찰자 불변식 포함)
└── backtest.py             # 전략 백테스트

alembic/                    # DB 마이그레이션
tests/                      # pytest 테스트
md/                         # 설계 문서
  ├── design/                   # 시스템 설계
  │   ├── bid_rate_definitions.md            ★ 투찰률·하한율 기준 (확정)
  │   ├── 2026-05-29-distribution-engine-analysis.md  ★ 사정률 예측 폐기 근거
  │   └── bidding_engine_design.md           (폐기 — 사정률 예측 시절)
  ├── data/                     # 데이터 수집 관련
  │   ├── data_collection.md
  │   └── data_collection_fixes.md
  ├── plans/                    # 실행 계획
  │   ├── plan_info21c.md
  │   └── implementation_plan.md
  ├── status/                   # 진행 상황 / 회의록
  │   └── progress.md
  ├── reference/                # 참고 자료
  │   └── 공공입찰_제도_가이드.md            ★ 제도 규칙 (하한율 개정, A값, 복수예가)
  └── raw/                      # 원본 데이터 파일 (csv, xlsx 등)
```

---

## 환경 설정

```bash
# .env (필수)
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/gonggong
G2B_API_KEY=your_api_key_here   # 비워두면 MockG2BFetcher 자동 사용
```

G2B_API_KEY가 없으면 `settings.use_mock_g2b = True`가 되어 Mock 데이터로 동작한다.

---

## 개발 서버 실행

```bash
uvicorn app.main:app --reload
```

---

## DB 마이그레이션 (Alembic)

```bash
# 마이그레이션 적용
alembic upgrade head

# 새 마이그레이션 생성
alembic revision --autogenerate -m "설명"
```

테이블: `bids_history`, `bid_participants`, `bid_license_types`,
`bid_preliminary_prices`, `client_statistics`, `project_bucket`

`project_bucket`은 초기 시드 데이터가 필요하다 (금액 구간 4개).

---

## 테스트

```bash
pytest tests/          # 백엔드
cd frontend && npx vitest run && npx tsc --noEmit
```

⚠️ 인자 없는 `pytest` 는 `logs/*.txt` 수집 단계에서 UnicodeDecodeError 로 죽는다.
반드시 `pytest tests/` 로 경로를 지정한다.

`pytest.ini`: `asyncio_mode = auto`

테스트 파일별 역할:
- `test_a_value.py` — A값 역산, 실효 하한율, A값 반영 투찰가·내 위치 (실측값 기반)
- `test_distribution.py` / `test_distribution_cache.py` — offset 히스토그램, fallback 스코프, 캐시
- `test_api_distribution.py` — 분포 엔드포인트 통합 테스트
- `test_spa_path_traversal.py` — SPA 폴백이 dist 밖 파일을 서빙하지 않는지
- `test_statistics.py` — trimmed_median, mad 순수 계산 검증
- `test_calculator.py` — 투찰가 계산 로직 검증
- `test_digit_filter_and_strategy.py` — 끝자리 필터, 전략 선택 검증
- `test_g2b_fetcher.py` — G2B API 파싱 검증 (MockG2BFetcher 사용)
- `test_fallback.py` — Fallback 레벨 선택 검증
- `test_api_bidding.py` — 엔드포인트 통합 테스트

---

## 최종 목표

1. **투찰 위치 판단 근거 제공** — 경쟁자 분포 위에서 내 타점이 어디인지 보여준다.
   등수의 분산을 줄이는 것이 목표지, 사정률을 맞히는 것이 아니다
2. **투찰 자동화** — 결정 후 나라장터에 직접 투찰 (수동 클릭 없이)
3. **낙찰률 3배 향상** — 현재 0.3~0.4% → 목표 1% 이상

### 주요 타겟 발주처
- **국방부** (연말 집중 물량)
- **교육청** (연중 높은 발주 빈도)
- **경기도 지자체** (조경·실내건축 물량 다수)

---

## 데이터 수집 파이프라인

현재 `bids_history` 약 18,400행 / `bid_participants` 적재 완료 (2026-08 기준).
적재 후에는 반드시 `python scripts/validate_data.py` 로 품질을 확인한다.
특히 **낙찰자 불변식**(낙찰자 투찰율 ≥ 법정 하한율)이 깨지면 하한율이 오염된 것이다.

### 경로 A: Info21c 자동 다운로드 (주 경로, 구현 완료)

```
scripts/info21c_downloader.py  ← Playwright 자동 다운로드 (구현됨, 셀렉터 검증 필요)
scripts/etl_csv.py             ← 클린 CSV → DB 적재 (구현됨)
```

**실행 순서:**
```bash
# 1. 설치 (최초 1회)
pip install playwright && playwright install chromium

# 2. 다운로드 (--debug 로 첫 실행 권장)
python scripts/info21c_downloader.py --start 20250101 --end 20251231 --debug

# 3. DB 적재
python scripts/etl_csv.py --file data/downloads/info21c_0002_20250101_20251231.csv
python scripts/etl_csv.py --file data/downloads/info21c_0023_20250101_20251231.csv
```

Info21c 접속: `https://www.info21c.net/` / ID `nw8856` / PW `nw8856` (동시 접속 불가, 오전 주의)
상세 계획: `md/plans/plan_info21c.md`

### 경로 B: G2B API 백필 (보완용, 미구현)

아래 파일들이 추가로 필요하다:

```
app/
├── db/crud_write.py            # bids_history UPSERT
├── external/g2b_collector.py   # 날짜 범위 일괄 수집
└── jobs/
    ├── __init__.py
    ├── collect.py              # 일별 수집 잡
    └── refresh_stats.py        # client_statistics 갱신 (선택)
```

설계: `md/data/data_collection.md` / 수정사항: `md/data/data_collection_fixes.md`

---

## G2B API 주요 주의사항

- **`bsnsDivCd` 필수**: scsbid API 호출 시 반드시 포함 (3=공사, 5=용역). 누락 시 에러코드 `08`
- **날짜 범위 제한**: scsbid API 1주일, 입찰공고 API 1개월. 초과 시 에러코드 `07`
- **날짜 형식**: `YYYYMMDDHHMM` (12자리)
- **`sucsfLwstlmtRt` 단위**: API는 퍼센트(%) 단위 → `/100` 변환 후 저장 (예: `89.745` → `0.89745`)
- **Rate Limit**: 30 tps → 요청 간 0.1초 지연
- **낙찰자 필터**: `sucsfYn=Y AND opengRsltDivNm=개찰완료`

---

## 코드 규칙

- 모든 금액은 `int` (원 단위, 소수점 이하 버림)
- 모든 비율은 `Decimal` (float 부동소수점 오류 방지)
- G2B API 키 없으면 Mock 자동 전환 — 로컬 개발 시 `.env`의 `G2B_API_KEY` 비워두면 됨
- `crud.py`는 읽기 전용, 쓰기는 `crud_write.py`에서 분리
- 낙찰하한율·A값은 **모르면 채우지 말고 실패시킨다** (위 '하지 말아야 할 것' 참고)

### 배포 서버는 RAM 1GB다 (설계 제약)

`bid.fp-desk.com` 은 OCI `VM.Standard.E2.1.Micro` — **1 OCPU / RAM 1GB**.
DB 가 703MB 라 페이지 캐시에 다 못 올라간다. **로컬 성능은 근거가 못 된다.**

2026-08-28 에 분포 요청이 참여자 4,490,354 행을 파이썬 리스트로 끌어오면서
서버가 스래싱으로 멈췄고 VM 을 강제 재부팅했다. 그래서:

- **행을 파이썬으로 끌어오지 말 것.** 집계는 SQL 에서 한다
  (`bid_participants` 4,656,914 행 / SQL 집계 시 RSS 14.6MB)
- **넓은 스코프는 사전계산.** `scripts/build_offset_histogram.py` 를 **로컬에서** 돌린다.
  ETL 로 데이터를 갱신했으면 이것도 다시 돌려야 한다
- **SQLite `alter_column` 금지.** 테이블 재작성을 유발한다. alembic autogenerate 가
  무관한 `NOT NULL` 변경을 끼워 넣으므로 마이그레이션은 눈으로 확인할 것
- **배포 전 서버에서 재라.** DB 파일만 `/tmp` 에 놓고 쿼리 시간·RSS 를 측정한 뒤 교체한다

상세: `docs/deployment.md` 10절

---

## Dev 세션 시작 프로토콜 (필수)

**모든 Dev 세션은 이 순서를 따른다:**

### 1. 다음 태스크 확인
`tasks.md`를 읽어 `status: pending` 중 우선순위가 가장 높은 태스크를 선택한다.
태스크를 시작하면 해당 항목의 status를 `in_progress`로 변경한다.

### 2. Why 재검토 (3가지 질문에 답하고 진행 여부 결정)
1. **지금도 이게 가장 중요한 작업인가?** — 더 급한 버그나 블로커가 생겼는가?
2. **이미 다른 방법으로 해결됐나?** — 이전 이터레이션에서 간접적으로 해결됐는가?
3. **아키텍처 방향과 맞나?** — 분포 기반 의사결정 도구 방향과 일치하는가?
   (절대 금지: 사정률 예측 강화, ML 기반 숫자 추천, 예정가격 예측)

→ **진행**: `tasks.md`에서 status `in_progress`로 변경 후 구현 시작
→ **스킵**: `tasks.md`에 skip 이유를 notes 필드에 기록하고 다음 태스크로

### 3. 구현 완료 후 handoff 작성
구현이 완료되면 `tasks.md`에서 status를 `done`으로 변경하고, 반드시 `eval-handoff.md`를 작성한다.

`eval-handoff.md` 형식:
```markdown
# Handoff — [태스크명] — [날짜]

## 변경한 파일
- `경로/파일명` — 무엇을 바꿨는가

## Eval 에이전트가 확인해야 할 포인트
- 구체적인 엔드포인트 URL, 예상 응답
- 프론트에서 봐야 할 화면/인터랙션

## 알려진 미해결 사항
- 이번에 해결 못한 것 (있으면 기재)
```
