# Handoff — T-033 데이터 오염 두 건 정정 — 2026-09-11

## 변경한 파일

- `app/engine/a_value.py` — `bid_rate_with_a_value()` 신설.
  `bid_price_with_a_value()` 의 역함수. 계산 불가면 None.
- `app/db/crud_distribution.py` — `_verifiable_limits_filter()` 신설,
  `_target_filters()` 에 추가. 낙찰하한가 없는 공고를 집계에서 뺀다.
- `scripts/info21c_participants.py` — 참여자 적재 시 원본 `투찰율` 대신
  투찰금액에서 재계산한 값을 쓴다 (예정가격 모르면 원본값 폴백).
- `scripts/repair_legal_limit_rate.py` — 신규. 일회성 정정 (dry-run 기본).
- `scripts/repair_bid_rate.py` — 신규. 일회성 정정 (dry-run 기본).
- `scripts/validate_data.py` — 불변식 보고를 집계 대상 / 제외분으로 분리.
- `tests/test_a_value.py` — 신규 4개 (역함수, A=0, 불가 입력, 실측 회귀).
- `tests/test_distribution_crud.py` — 신규 2개 (검증 불가 공고 제외).
- `tests/test_distribution_precompute.py` — 픽스처에 `lower_limit_price` 추가.

## Eval 에이전트가 확인해야 할 포인트

**1. 분포에서 검증 불가 공고가 빠지는가**

```bash
python -m pytest tests/test_distribution_crud.py -q -k "lower_limit_price"
```
낙찰하한가가 없거나 0 인 공고의 참여자가 집계에 남으면 회귀다.

**2. 투찰율 재계산이 불변식을 회복하는가**

```bash
python -m pytest tests/test_a_value.py -q -k "bid_rate_with_a_value"
```
실측 회귀 케이스: R25BK01182094-000 은 저장값 0.833984 로 하한 0.87745 를
밑돌았다. 재계산하면 0.877476 로 하한 바로 위다.

**3. 정정 스크립트는 dry-run 이 기본인가** — `--apply` 없이 돌려 DB 가
안 바뀌는지 확인. 프로젝트 관례(backfill_a_value.py)와 같다.

**4. DB 상태 (2026-09-11 정정 후)**
```
legal_limit_rate 오염     1 (판별 불가분)
낙찰자 불변식 위반        244  → 집계 대상 내 15 (0.10%), 제외분 229
집계 제외 공고            877 / 16,307 (5.4%)
offset_histogram          9,280 bin / 19 스코프
```

**5. 화면 회귀** — `/distribution` 에서 주요 발주처 조회 시 히스토그램이
그려지는지. 투찰율 62.8만 행이 바뀌었으므로 분포 모양이 미세하게 다르다.
표본 수가 급감했다면(예: 평택시 489 → 수백 단위 이하) 필터가 과하게 잡은 것이다.

## 알려진 미해결 사항

- **집계 대상 내 불변식 위반 15건.** 낙찰하한가가 있는데도 어긋난다.
  개별 확인 필요. 엔진은 `_trusted_limits_filter()` 로 이미 제외한다.
- **`adjustment_rate` 범위 이탈 215건.** 이번 작업 범위 밖.
- **고아 공고 235건** (T-032 에서 이월). 시기 특정 불가.
- **주말이 매번 미수집으로 잡힌다** (T-032 에서 이월).
