# Handoff — 프론트 A값 입력 (3단계) — 2026-08-27

A값 파이프라인(1단계)과 하한율 정합성 복구(2단계)는 백엔드까지만 되어 있었다.
화면에 A값 입력 필드가 없어 실사용이 불가능했다. 이번에 그 마지막 구간을 연결했다.

---

## 핵심 — my_position 도 A값 조정이 필요하다

분포 x축은 원본 `투찰율(%)` = `(투찰금액 − A) / (예정가격 − A)` 기준이다
([md/design/bid_rate_definitions.md](md/design/bid_rate_definitions.md)).
내 위치만 `투찰금액 / 기초금액` 으로 재면 A값 크기만큼 오른쪽으로 밀린다.

```
my_offset ≈ (my_bid_price − A) / (base_price − A) − 법정하한율     (사정률≈1.0 근사)
estimated_price = (base_price − A) × (법정하한율 + offset) + A
```

기초금액 1억 / A값 500만 / 하한율 87.745% 인 공고에서 A값을 빼먹으면
**+0.64%p** 어긋난다. bin 해상도가 0.1% 이므로 6~7칸 밀린 위치가 표시된다.

---

## 변경한 파일

### 백엔드
- `app/engine/distribution.py` — `calc_my_position(..., a_value=0)`.
  조정 투찰율로 offset 계산, `estimated_price` 도 역변환 대칭으로 수정.
  A값이 기초금액 이상이면 이상값으로 보고 무시
- `app/api/v1/distribution.py` — `overrides.a_value` 수신 → `calc_my_position` 전달 → 응답에 반영
- `app/schemas/distribution.py` — `DistributionResponse.a_value`.
  `lower_limit_rate` 설명을 "법정 낙찰하한율 (A값 제외 기준선)" 으로 명시

### 프론트
- `frontend/src/lib/api.ts` — `DistributionResult.a_value`
- `frontend/src/lib/distribution.ts` — `computeLocalPosition(..., aValue = 0)`.
  백엔드와 동일 산식
- `frontend/src/pages/BidCalculator.tsx` — `A값 (원)` 입력 필드 + 안내 문구.
  하한율 placeholder `0.87745` → `0.89745` (2026 현행값)
- `frontend/src/pages/BidDistribution.tsx` — `A값 (원)` 입력 필드,
  `overrides.a_value` 전송, `computeLocalPosition` 에 전달,
  공고 메타에 A값 표시(0이면 숨김), 누락 시 경고 문구

### 테스트
- `tests/test_a_value.py` — `calc_my_position` A값 테스트 5개 추가 (총 30개)
- `frontend/src/lib/distribution.test.ts` — A값 테스트 5개 추가 (총 45개)

---

## Eval 에이전트가 확인해야 할 포인트

### 1. 분포 화면에서 A값 입력 — `/distribution`

`A값 (원)` 필드에 값을 넣고 조회 → 공고 메타에 `A값: n원` 이 뜬다.
같은 투찰가로 A값을 넣었을 때와 비웠을 때 **내 위치 마커가 좌우로 움직여야** 한다.
A값을 넣은 쪽이 왼쪽(하한선에 가까운 쪽)이다.

### 2. 계산기 화면 — `/calculator`

`A값 (원)` 입력 시 `bids[].price_krw` 가 올라가고 `a_value` 가 응답에 실린다.
비우면 기존 결과와 완전히 동일해야 한다 (회귀 확인).

### 3. 테스트

```bash
python -m pytest tests/ -q                 # 183 passed
cd frontend && npx tsc --noEmit            # 에러 없음
cd frontend && npx vitest run              # 81 passed
```

---

## 알려진 미해결 사항

1. **A값은 여전히 수동 입력이다.** G2B 개방표준 API에 항목이 없다.
   [나라장터 입찰공고정보서비스 (15129394)](https://www.data.go.kr/data/15129394/openapi.do)
   활용신청이 필요하다 (현재 키 미등록 — 에러코드 30 확인).

2. **붙여넣기 A값 추출 — 2026-08-27 완료.** `parseInfo21cText` 가 명시 금액 →
   낙찰하한가 역산 순으로 A값을 채우고, 태그만 있고 금액을 못 찾으면 화면에 경고한다.
   남은 것: **공고번호 조회 경로**는 아직 `bids_history.has_a_value` 를 보지 않는다.
   붙여넣기 없이 공고번호만 입력하면 A값 힌트가 없다.

3. 이하 이전 단계의 미해결 사항은 아래 핸드오프 참고.

---
---

# 이전 핸드오프

# Handoff — 낙찰하한율 정합성 복구 (2단계) — 2026-08-27

아래 "이전 핸드오프 — A값 파이프라인"에 이어지는 작업이다.
A값 산식·컬럼·계산기는 이미 들어가 있었지만, **불변식 위반은 241/362 (66.6%) 그대로**였다.
마이그레이션이 기존 18,409행에 `effective_limit_rate = lower_limit_rate`(오염된 값)를
그대로 복사했기 때문이다.

기준 정의 확정(1단계) 산출물: [md/design/bid_rate_definitions.md](md/design/bid_rate_definitions.md)

---

## 핵심 발견 — 기준선은 실효 하한율이 아니라 법정 하한율이다

원본 `투찰율(%)` (→ `bid_participants.bid_rate`) 은 **이미 A값이 제거된 조정 투찰율**이다.

```
투찰율 = (투찰금액 - A) / (예정가격 - A)
```

`R26BK01359312-000` (A값 99.5억):
- 투찰금액 25,084,928,400 / 예정가격 28,098,535,925 = 0.892749 → 투찰율과 **불일치**
- (25,084,928,400 - A) / (28,098,535,925 - A) = 0.833956 = 투찰율 83.3955% ✓

A값 0인 공고에서는 두 정의가 일치해서 구분되지 않는다. 그래서 놓치기 쉽다.

실측 (하한율 갱신 완료 223건):

| offset 기준선 | 낙찰자 불변식 위반 |
|---|---|
| `legal_limit_rate` | **0 / 223** |
| `effective_limit_rate` | 191 / 223 |

기준선을 실효로 잡으면 A값이 이중 차감되어 **위반이 66.6% → 70.7% 로 악화**된다.

---

## 변경한 파일

### `scripts/etl_participants.py` — 원본 하한율을 bids_history 로 전달

기존 파서는 공고 헤더의 `낙찰하한율`/`낙찰하한가`를 **한 번도 읽지 않았다**
(독스트링에는 위치가 적혀 있었다). 이것이 하한율 오염의 근본 원인이다.

- `_cell_after()` / `_first_amount()` / `_declared_a_value()` 헬퍼 추가.
  레이아웃이 파일마다 달라 (row, col) 고정 인덱스 대신 라벨 문자열로 찾는다
- `parse_notice()` — 기초금액 / 예정가격 / 낙찰하한율 / 낙찰하한가 / 선언 A값 파싱
- `parse_xls()` 반환에 `notice` 추가
- `update_notice_limits()` + `UPDATE_LIMITS_SQL` — `a_value.split_limit_rates()` 로
  (법정, 실효, A값) 분리 후 `bids_history` 갱신
- `--update-limits` 플래그 (기본 off, `--dry-run` 존중)
- 원본이 A값을 직접 선언한 경우 역산값과 대조해 불일치를 출력

### `app/db/crud_distribution.py` — offset 기준선 정정

`COALESCE(effective_limit_rate, lower_limit_rate)` → `COALESCE(legal_limit_rate, lower_limit_rate)`.
근거를 docstring 에 명시했다.

### `scripts/validate_data.py`

- **낙찰자 불변식 검사 추가** (6번 항목). 위반 10% 이상이면 FAIL.
  이 검사가 처음부터 있었으면 241건이 들어오는 순간 잡혔다
- `project_type` 컬럼 참조 수정 — 앞선 마이그레이션으로 `bid_license_types` 로
  이관됐는데 검증기가 옛 컬럼을 보고 있어 전체가 크래시했다 (기존 버그)

### `md/design/bid_rate_definitions.md`

1단계 확정 문서. 이번에 초판의 오류를 정정했다 —
초판은 `offset = 투찰금액/낙찰하한가 - 1` 을 권고했으나, 검증 표본이 전부 A값 0인
공고여서 투찰율의 A값 조정을 놓친 결과였다. 5절에 정정 사유를 명시했다.

---

## 실행 결과

```bash
python scripts/etl_participants.py --update-limits
```

```
[하한율 갱신] 대상=255 / 판별불가=32 / bids_history에 없음=49 / A값 불일치=0
  255건 갱신 완료
```

**A값 불일치 0** — 역산 A값이 원본 선언 A값과 276/276 전부 일치한다.
산식과 파서가 동시에 검증됐다.

### 불변식 회복

| 시점 | 낙찰자 위반 |
|---|---|
| 작업 전 | 241 / 362 (66.6%) |
| 갱신분 223건 | **0** |
| 전체 | 65 / 362 (18.0%) |

### 법정 하한율 분포 (참여자 보유 공고)

갱신 전에는 42.3%가 `0.87745` 하드코딩이었다. 이제 실제 값이 들어왔다.

```
0.877450  159건    0.867450   66건    0.897450  29건    0.813950  23건
0.859950   10건    0.887450    7건    0.833950   6건    0.879950   4건
```

---

## Eval 에이전트가 확인해야 할 포인트

### 1. 분포 피크의 부호가 뒤집혔는지 — `POST /api/v1/bid/distribution`

```bash
curl -X POST http://localhost:8000/api/v1/bid/distribution   -H "Content-Type: application/json"   -d '{"bid_notice_id":"TEST-001","overrides":{"base_price":800000000,"lower_limit_rate":0.87745,"client_name":"서울주택도시공사","region":"서울","project_type":"실내건축"}}'
```

실측 결과 (level=client, notices=40, bins=103):

| offset | count | win |
|---|---|---|
| +0.1% | 999 | **27** |
| +0.2% | 986 | 7 |
| +0.3% | 920 | 8 |
| +0.4% | 906 | 1 |

- 갱신 전 피크는 `-0.6%` — 하한 미달이라 물리적으로 불가능한 위치였다
- 갱신 후 피크가 `+0.1% ~ +0.8%` (하한 위)로 이동해야 한다
- 낙찰 40건 중 27건이 `+0.1%` bin 에 몰린다 — 낙찰자가 하한선에 붙는다는 실무와 일치
- 프론트 `BidDistribution` 화면에서 히스토그램이 0 오른쪽에 서는지 눈으로 확인

### 2. 데이터 검증기

```bash
python scripts/validate_data.py
```

현재 `재수집 필요` — `낙찰자 불변식 위반 18.0%` 로 FAIL 한다. **의도된 동작이다.**
남은 65건을 처리하면 통과한다. 이 검사가 0%로 떨어지는 것이 완료 조건이다.

### 3. 테스트

```bash
python -m pytest tests/ -q     # 178 passed
```

`pytest` 를 인자 없이 돌리면 `logs/*.txt` 수집 UnicodeDecodeError 로 실패한다 — 기존 문제.

### 4. 백업 위치

`bids_history` 하한율 계열 컬럼 18,409행 전체를 갱신 전에 백업했다:
`<scratchpad>/bids_history_limits_backup.csv`
(`project_id, lower_limit_rate, legal_limit_rate, effective_limit_rate, a_value, has_a_value`)

---

## 알려진 미해결 사항

1. **남은 불변식 위반 65건 (18.0%).** 전부 A값 0이고 원본에 낙찰하한가가 없어
   갱신하지 못했다. 24건은 여전히 `0.87745` 하드코딩. 원본 409개 중 100개에
   하한율이 없다. G2B API `sucsfLwstlmtRt` 로 보완할지 결정 필요.

2. **`bid_participants.vs_lower_limit` 컬럼명·주석이 틀렸다.**
   실제 내용은 원본 `업체별사정율(%)` 이다. 모델 주석은
   "예비가격대비율 (낙찰하한율 기준 차이, %p)" 이라고 되어 있어 오독을 유발한다.
   이 컬럼으로 하한율을 역산하면 안 된다. 컬럼명 마이그레이션 필요.

3. **`0.87745` 하드코딩 fallback 이 3곳에 남아 있다** —
   `etl_csv.py:128`(요약 포맷), `g2b_collector.py:334`, `g2b_fetcher.py:124`.
   모르는 값을 아는 척 저장하는 것이 이번 오염의 근본 원인이므로 `None` 으로
   바꾸는 것이 맞다. 다만 `lower_limit_rate` 가 NOT NULL 이라 스키마 변경이 따라온다.

4. **bin 해상도 재설계.** `_BIN_PCT_RESOLUTION = 1` (0.1%) 로는 낙찰자 p25~p75
   (+0.0013% ~ +0.0405%) 가 전부 한 bin 에 뭉친다. 참여자 분포는 103개 bin 에
   퍼지고 0.0% 쏠림이 3.2% 라 막대그래프 자체는 깨지지 않아 급하지는 않다.

5. **`etl_participants.py` 파싱 실패 73건.** 참여자 섹션을 못 찾은 파일들로,
   이 중 일부는 공고 헤더에 하한율이 있어 회수 여지가 있다.

6. **Taskmaster 미연동.** `get_next_task` / `set_task_status` 프로토콜을 수행하지 못했다.

---
---

# Handoff — A값(법정경비) 파이프라인 — 2026-08-27

적격심사 낙찰하한가는 `예정가격 × 하한율`이 아니라 `(예정가격 − A값) × 하한율 + A값`이다.
A값을 무시하면 하한가 아래로 투찰해 **부적격 탈락**한다.
Info21c `입찰리스트` 엑셀 실측 결과 **81건 중 57건(70%)이 A값 공고**였다.

제도 배경 전체: [md/reference/공공입찰_제도_가이드.md](md/reference/공공입찰_제도_가이드.md) 6장

---

## 변경한 파일

### 신규
- `app/engine/a_value.py` — A값 코어 로직
  - `has_a_value_tag()` — Info21c 공고명의 `[A값]` 태그 파싱
  - `resolve_legal_limit_rate()` — 실효 하한율에서 법정 하한율 역추정 (후보표 스냅다운)
  - `derive_a_value()` — `A = (낙찰하한가 − 예정가격×r) / (1−r)`
  - `effective_limit_rate()`, `bid_price_with_a_value()`, `split_limit_rates()`
- `alembic/versions/d5c7b39a4e10_add_a_value_and_limit_rate_split.py` — 컬럼 4개 추가 + 기존 행 백필
- `scripts/backfill_a_value.py` — 과거 적재분 법정/실효 분리 백필 (**dry-run 기본, 아직 미적용**)
- `tests/test_a_value.py` — 25개 테스트 (실측 데이터 기반)

### 수정
- `app/db/models.py` — `BidsHistory`에 `a_value`, `has_a_value`, `legal_limit_rate`, `effective_limit_rate` 추가.
  `lower_limit_rate`는 하위 호환용으로 유지
- `scripts/etl_csv.py`
  - 요약 포맷의 `낙찰하한율 = 0.87745` 상수 하드코딩 **제거** (가짜 법정값이었음) → `None`으로 두고 낙찰하한가에서 역추정
  - `_parse_amount()` / `_parse_rate()` 헬퍼 추가
  - `split_limit_rates()`로 법정/실효/A값 분리 저장
  - 적재 요약에 A값 통계 출력
  - `--upsert` 플래그 추가 (신규 컬럼 백필용)
- `app/engine/calculator.py` — `calculate_single()` / `calculate_bid_spread()`에 `a_value` 파라미터.
  공식이 `(예정가격 − A) × (LLR + offset) + A`로 변경. **a_value=0이면 기존 결과와 완전히 동일**
- `app/db/crud_distribution.py` — offset 기준선을 `COALESCE(effective_limit_rate, lower_limit_rate)`로 변경
- **낙찰하한율 기본값 제거** (2026-08-27 추가 작업)
  - `app/external/g2b_fetcher.py` — `sucsfLwstlmtRt` 없으면 `None` 반환. `G2BNoticeData.lower_limit_rate: Decimal | None`
  - `app/external/g2b_collector.py` — 없으면 `ValueError` → 해당 건 스킵 (DB에 가짜 하한율이 들어가던 경로)
  - `app/api/v1/bidding.py` · `app/api/v1/distribution.py` — `None`이고 override도 없으면 **400** + 입력 안내
  - `scripts/validate_data.py` — "0.87745 고정 비율" 점검을 "법정 하한율 미판별 비율"로 교체 (+ A값 현황 출력)
- `app/schemas/request.py` — `BidOverrides.a_value`
- `app/schemas/response.py` — `BidItem.a_value`
- `app/api/v1/bidding.py` — a_value override 전달

---

## Eval 에이전트가 확인해야 할 포인트

### 1. A값 반영 투찰가 — `POST /api/v1/bid/calculate`

실측 공고(학생회관 승강기 설치 공사) 기준. 예정가격 328,577,900 / 낙찰하한가 289,985,144 / 법정 하한율 0.88 / A값 6,971,600.

```json
{
  "bid_notice_id": "R25BK00828581-000",
  "overrides": { "base_price": 328577900, "lower_limit_rate": 0.88, "a_value": 6971600 }
}
```

- `bids[0].price_krw`가 A값 없이 계산한 값(≈289,148,552)보다 **약 836,592원 높아야** 한다
- `bids[0].a_value`가 6971600으로 응답에 실려야 한다
- `a_value`를 빼고 같은 요청을 보내면 기존 동작과 동일해야 한다 (회귀 확인)

### 2. ETL 실행 결과

```bash
python scripts/etl_csv.py --file data/downloads/info21c_0002_20250501_20250515.xlsx --upsert
```

실행 확인됨. 출력:
```
DB 적재 대상: 56건
A값: 적용 공고 49건 / 역산 성공 48건, 기초금액 대비 평균 2.11%
```

DB 확인 쿼리:
```sql
SELECT COUNT(*) FILTER (WHERE has_a_value) tagged,
       COUNT(*) FILTER (WHERE a_value > 0)  derived,
       COUNT(*) FILTER (WHERE legal_limit_rate IS DISTINCT FROM effective_limit_rate) split
FROM bids_history;
```
→ 현재 49 / 48 / 49

### 3. 분포 화면 — `POST /api/v1/bid/distribution`

offset 기준선이 실효 하한율로 바뀌었다. A값 공고가 섞인 표본에서 **분포 봉우리가 왼쪽(0%쪽)으로 이동**해야 한다.
기존에는 A값만큼 오른쪽으로 밀려 보였다. 프론트 `BidDistribution` 화면에서 히스토그램 중심 위치를 눈으로 확인할 것.

### 4. 테스트

```bash
python -m pytest tests/ -q     # 178 passed
```
`pytest` (인자 없이)는 `logs/*.txt` 수집 에러로 실패한다 — **기존 문제**이지 이번 변경과 무관.

---

## 알려진 미해결 사항

1. **과거 적재분 18,361건 백필 미적용.**
   `scripts/backfill_a_value.py` dry-run 결과 **11,568건 갱신 대상 / 11,474건에서 A값 발견**.
   추정 기반이라 18k 행을 건드리는 판단은 보류했다. 적용하려면 `--apply`.
   원본 엑셀이 있으면 `etl_csv.py --upsert` 재적재가 항상 더 정확하다.

2. **법정 하한율 역추정의 한계.**
   `LEGAL_LIMIT_RATES` 후보표에 실효 하한율을 스냅다운하는 방식이라,
   A값이 커서 실효 하한율이 바로 위 후보를 넘어서면 **A값이 과소평가**된다.
   원본에 `낙찰하한율` 컬럼이 있으면 이 문제는 발생하지 않는다 (declared 우선).

3. **G2B 경로에는 A값이 없다.**
   현재 쓰는 개방표준 API 2개(`getDataSetOpnStdBidPblancInfo` / `...ScsbidInfo`)에 A값 항목이 없어
   `/bid/calculate`는 override로만 A값을 받는다.
   [나라장터 입찰공고정보서비스 (15129394)](https://www.data.go.kr/data/15129394/openapi.do) 활용신청이 필요하다
   (현재 키는 미등록 — `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` 확인됨).

4. **프론트 미변경.** `BidCalculator` / `BidDistribution` 화면에 A값 입력 필드가 없다.
   현재는 API 직접 호출로만 A값을 넣을 수 있다.

5. **`scripts/validate_data.py` 후반부가 죽는다 — 기존 버그.**
   `공종별/버킷별 분포` 섹션이 `bids_history.project_type`을 조회하는데,
   그 컬럼은 `bid_license_types` 테이블로 분리되면서 사라졌다 → `UndefinedColumnError`.
   이번 변경과 무관하며, 앞쪽 검증 항목은 정상 출력된다.

6. **Taskmaster 미연동.** 이 세션에서 Taskmaster MCP를 쓸 수 없어
   `get_next_task` / `set_task_status` 프로토콜을 수행하지 못했다. 태스크 상태 수동 갱신 필요.
