# Handoff — 분포 엔진 출력 정상화 (T-009 / T-010 / client_id) — 2026-08-25

## 배경

`bid.fp-desk.com` 공개 후 기능 점검에서, 엔진이 **돌기는 하지만 출력이 쓸 수 없는 상태**임을 확인했다.
실제 공고 조건(경기 화성시·조경·기초금액 8.7억)으로 호출한 결과:

| 항목 | 수정 전 | 수정 후 |
|---|---|---|
| `offset_pct` 범위 | **-178.4% ~ +1729.4%** | **-34.7% ~ +14.9%** |
| 히스토그램 구간 수 | 230 | 182 |
| `estimated_participants` | **4** | **578** |
| 최다 구간 | (축이 망가져 의미 없음) | -0.9% / -1.0% / -1.2% (각 1,000건대) |

## 변경한 파일

- `app/db/crud_distribution.py`
  - `_RATE_SANITY_FILTERS` 추가 — 조회 시 `0.5 <= bid_rate <= 1.05` 인 행만 쓴다
  - `_is_usable_client_id()` 추가 — 문자열 `'None'` 을 client 필터로 쓰지 않는다
  - `get_avg_participants()` 의 `base` 를 `_RELAX_FILTERS` 로 교체 (strict → 완화)
  - `get_avg_participants()` 내부 `_avg()` 에 `join_license` 플래그 추가 — 공종 조건을 쓰는 레벨에서만 join
- `tests/test_distribution_crud.py` (신규) — in-memory SQLite 로 위 4가지를 검증하는 6개 테스트
- `tasks.md` — T-009 / T-010 done, T-003 에 원인 규명 기록

## 고친 버그 4가지

1. **bid_rate 이상치 유입 (T-010)** — `_fetch_offset_rows` 에 범위 조건이 없어, `bid_amount=99999999999999` 더미행(2,271)·음수 rank 파싱오류행(232)·자리수 깨짐(1,916)이 히스토그램에 그대로 들어갔다.
2. **참여자 수 저평가 (T-009)** — `get_avg_participants` 만 `price_method='복수예비가격'` strict 였다. 실 DB 의 97% 가 `'기타'` 라 표본이 붕괴했다.
3. **공종 수만큼 가중 (신규 발견)** — `_avg()` 가 공종 조건을 안 쓰는 레벨에서도 `BidLicenseType` 을 join 해, 공고 하나가 공종 수(최대 14개)만큼 중복 계산됐다. 2번만 고쳤을 때 1071 이 나온 원인.
4. **client_id 죽은 컬럼** — 전 행이 문자열 `'None'` 인데 truthy 라, `client_id == 'None'` 필터가 서면 모든 발주처가 한 덩어리로 매칭됐다.

## Eval 에이전트가 확인해야 할 포인트

로컬에서 `uvicorn app.main:app --port 8010` 후:

```bash
POST http://127.0.0.1:8010/api/v1/bid/distribution
{"bid_notice_id":"T","my_bid_price":1638681998,
 "overrides":{"base_price":1821868887,"lower_limit_rate":0.8819788758084542,
              "client_name":"경기도 화성시","region":"경기","bid_type":"적격심사","project_type":"조경"}}
```

- `distribution` 의 `offset_pct` 최소/최대가 **-40% ~ +20% 안**에 들어오는가
- `estimated_participants` 가 수백 단위인가 (실 DB 공고당 평균 374.9명)
- 프론트 `BidDistribution` 히스토그램의 x축이 읽히는 범위인가 — **이 화면은 이번에 확인하지 못했다**

## 알려진 미해결 사항

- **ETL 근본 수정 안 됨.** 조회 시점에서만 막았다. `scripts/etl_participants.py` 가 계속 이상치를 넣고 있다.
- **`offset` 하한 -34.7% 잔존.** `bid_rate` 0.5~0.8 구간(9,862행)은 낙찰하한율이 낮은 공고에서는 정상일 수 있어 남겨 뒀다. 판단 필요.
- **`client_id` 컬럼 자체는 여전히 전 행 `'None'`.** 우회만 했고 값을 채우지 않았다. client 레벨 fallback 은 `client_name` 으로만 선다.
- **서버 배포 안 함.** 서버 DB 는 여전히 467건짜리 낡은 스냅샷이고, 서버 git 브랜치 이동이 auto 모드 분류기에 막혀 코드 동기화도 못 했다.
- **프론트엔드 미확인.** 백엔드 응답만 검증했다.
