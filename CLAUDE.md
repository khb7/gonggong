# CLAUDE.md — 공공입찰 통계 엔진

## 프로젝트 개요

나라장터(G2B) 공공입찰 데이터를 기반으로 **사정률을 예측하고 투찰가를 계산**하는 FastAPI 백엔드.
실내건축·조경 공종을 주 대상으로 한다.

핵심 흐름:
```
POST /api/v1/bid/calculate
  → G2B API (공고 1건 조회: 기초금액, 하한율, 발주처, 지역)
  → bids_history 에서 Fallback 기반 사정률 데이터 조회
  → Trimmed Median + MAD 통계 계산
  → Multi-Shot Bid Spread (Aggressive / Normal / Safe 3가지 투찰가)
```

---

## 도메인 핵심 개념

| 용어 | 설명 |
|------|------|
| **기초금액** (base_price) | 발주처가 내부적으로 설정한 예정가격의 기준 금액 (원) |
| **낙찰하한율** (lower_limit_rate) | 예정가격 대비 입찰 가능한 최저 비율 (예: 0.87745) |
| **사정률** (adjustment_rate) | 실제 낙찰가 ÷ 기초금액 (예: 0.899) |
| **예정가격** | 개찰 시 공개되는 실제 낙찰 기준가. = base_price × predicted_rate |
| **Fallback** | 발주처→지역→공종+버킷→전체 순으로 통계 데이터를 조회하는 계층형 로직. 각 레벨 최소 20건 필요 |
| **버킷** (bucket_id) | 기초금액 구간 분류 (1: ~1억, 2: 1억~5억, 3: 5억~20억, 4: 20억+) |

투찰가 공식:
```
최종 투찰가 = base_price × predicted_rate × (lower_limit_rate + offset)
```

---

## 디렉토리 구조

```
app/
├── api/v1/bidding.py       # POST /bid/calculate 엔드포인트
├── core/config.py          # 환경변수 설정 (DATABASE_URL, G2B_API_KEY)
├── data/fallback.py        # 계층형 Fallback 로직 (client→region→bucket→global)
├── db/
│   ├── models.py           # BidsHistory, ClientStatistics, ProjectBucket ORM
│   ├── crud.py             # bids_history 읽기 전용 쿼리
│   └── session.py          # AsyncSession, Base
├── engine/
│   ├── calculator.py       # 투찰가 계산 (calculate_single, calculate_bid_spread)
│   ├── statistics.py       # trimmed_median(), mad()
│   ├── strategy.py         # select_strategy(), generate_bid_spread()
│   └── digit_filter.py     # 끝자리 블랙리스트 회피
├── external/
│   └── g2b_fetcher.py      # G2BFetcher (실제), MockG2BFetcher (테스트용)
└── schemas/
    ├── request.py          # BidRequest
    └── response.py         # BidResponse

alembic/                    # DB 마이그레이션
tests/                      # pytest 테스트
md/                         # 설계 문서
  ├── data_collection.md        # 수집 파이프라인 설계
  ├── data_collection_fixes.md  # 설계 수정사항
  └── bidding_engine_design.md  # 엔진 설계
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

테이블: `bids_history`, `client_statistics`, `project_bucket`

`project_bucket`은 초기 시드 데이터가 필요하다 (금액 구간 4개).

---

## 테스트

```bash
pytest
```

`pytest.ini`: `asyncio_mode = auto`

테스트 파일별 역할:
- `test_statistics.py` — trimmed_median, mad 순수 계산 검증
- `test_calculator.py` — 투찰가 계산 로직 검증
- `test_digit_filter_and_strategy.py` — 끝자리 필터, 전략 선택 검증
- `test_g2b_fetcher.py` — G2B API 파싱 검증 (MockG2BFetcher 사용)
- `test_fallback.py` — Fallback 레벨 선택 검증
- `test_api_bidding.py` — 엔드포인트 통합 테스트

---

## 미구현 / 진행 중인 작업

### 데이터 수집 파이프라인 (최우선)

현재 `bids_history`가 비어있어 fallback이 항상 `"none"` / `predicted_rate: 1.0`을 반환한다.
아래 파일들을 추가로 구현해야 한다:

```
app/
├── db/crud_write.py            # bids_history UPSERT (INSERT ON CONFLICT DO NOTHING)
├── external/g2b_collector.py   # 날짜 범위 일괄 수집 (G2BCollector)
└── jobs/
    ├── __init__.py
    ├── collect.py              # 일별 수집 잡
    └── refresh_stats.py        # client_statistics 갱신 (선택)

scripts/
└── backfill.py                 # 과거 데이터 초기 적재
```

설계: `md/data_collection.md`
수정사항: `md/data_collection_fixes.md` — 구현 전 반드시 확인

**Critical 수정 2개 (구현 전 필수):**
1. `BidsHistory.project_id`에 `unique=True` 추가 + Alembic 마이그레이션
2. `G2BCollector.collect_range()` 내부에서 1주일 단위 분할 처리

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
- `crud.py`는 읽기 전용, 쓰기는 `crud_write.py`(미구현)에서 분리
