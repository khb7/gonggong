# Handoff — T-011 ETL이 버리는 원본 컬럼 적재 — 2026-08-26

## 배경

`data/downloads/*.xlsx`(160개, 13,592행)는 20개 컬럼인데 `etl_csv.py`가 일부만 읽고 나머지를 버리고 있었다.
버려지던 것 중 셋이 분석을 막고 있었다:

1. **공고명** — 대괄호 태그(`[A값][관내][순]`)가 참여자 수를 크게 가르는데 컬럼 자체가 DB에 없었다
2. **사정률** — 원본 `예가/기초(100%)`가 진짜 사정률(예정가격/기초금액)인데 미적재.
   기존 `adjustment_rate`는 `winner_price/base_price`(=1순위기초대비)라 **이름과 내용이 다르다**
3. **예정가격·낙찰하한가 원값** — 비율로 뭉갠 뒤 버려서 A값 역산이 불가능했다

재다운로드는 불필요했다. 전부 이미 받아둔 파일 안에 있었고 적재 단계에서만 빠졌다.

## 변경한 파일

- `alembic/versions/d52b7a3e6c14_add_notice_tags_and_preprice.py` (신규)
  - `bids_history` + `notice_title`, `preprice_rate`, `est_price`, `lower_limit_price`, `has_a_value`
  - `bid_tags` 테이블 신설 (`project_id`, `tag`) — `bid_license_types`와 같은 1:N 패턴
  - 전부 nullable. 재적재 전 행은 NULL이라 '미판정'과 False가 구분된다

- `app/db/models.py`
  - `BidsHistory`에 위 5개 컬럼 추가
  - `BidTag` 모델 추가

- `scripts/etl_csv.py`
  - `parse_notice_tags()` 추가 — 공고명 대괄호 파싱
  - `_sync_tags()` 추가 — 태그를 공고명과 **정확히 일치**시킨다(추가만 하면 정정공고로
    태그가 누적되어 `has_a_value`와 어긋난다. 실제로 9건 불일치가 났고 이 방식으로 고쳤다)
  - 사정률: 원본 컬럼 우선 → 없으면 `예정가격/기초금액` 폴백 → ±10% 벗어나면 버림
  - **upsert 경로에도 태그 삽입 추가.** `bid_license_types`는 신규 공고에만 넣는 구조라,
    기존 12,445건이 전부 upsert를 타는 재적재에서는 태그가 하나도 안 들어갈 뻔했다

- `scripts/backfill_participant_rates.py` (신규)
  - `bid_participants.base_rate` / `vs_lower_limit`를 **재파싱 없이 계산**으로 채운다
  - 참여자 원본 xls는 구글드라이브에 539개만 남아 있고 DB엔 12,000여 공고분이 있어 재파싱 자체가 불가능

## 실행한 것

```
cp data/gonggong.db data/gonggong.db.bak-20260826
python -m alembic upgrade head                      # 8d3110058ed9 → d52b7a3e6c14
for f in data/downloads/*.xlsx; do python scripts/etl_csv.py --file "$f" --upsert; done
python scripts/backfill_participant_rates.py
```

## 검증 결과

| 항목 | 기준 (원본 xlsx 직접 측정) | DB 결과 | 판정 |
|---|---|---|---|
| `preprice_rate` 평균 | 0.999151 | **0.999162** | OK |
| `preprice_rate` sd | 0.007287 | **0.007059** | OK |
| `has_a_value` ↔ `[A값]` 일치 | 0건 불일치 | 0건 (`_sync_tags` 수정 후) | OK |
| `base_rate` 재계산 검증 | 0건 불일치 | 0건 | OK |
| `vs_lower_limit` 재계산 검증 | 0건 불일치 | 0건 | OK |
| `bid_tags` | 태그별 비율 일치 | 44,817행 / 11,962공고 | OK |

`preprice_rate` sd 0.0071은 복수예비가격 이론값(강민석·류문찬 2015: 균등분할 ±3% → 0.00767)과 일치하며,
평균 0.9992는 같은 논문의 비균등분할-A1(지자체 채택 방식) 예측 **99.9%** 와 맞는다.
**전 표본이 복수예비가격 적격심사임이 실증됐다** — `etl_csv.py:136`의 `낙찰방법="적격심사"` 하드코딩은
출처가 없을 뿐 값 자체는 옳다.

### 신규로 가능해진 분석

`lower_limit_price / est_price`를 A값 유무로 분리하면:

```
[A값 없음] n=1,414   distinct 9개    0.87745(46%) 0.88(30%) 0.87995(17%)   ← 규정상 이산값
[A값 있음] n=10,154  distinct 2,667 (26.3%)                                ← 연속
```

`lower_limit_rate`의 distinct 11,370개는 **오염이 아니라 A값 효과**였다.
A값 공고는 `낙찰하한가 = (예정가격−A)×하한율 + A` 구조라 실효 하한율이 공고마다 다르다.
전체의 82%가 A값 공고이므로, **offset 히스토그램은 A값 유무로 분리해야 한다**(미적용).

## Eval 에이전트가 확인해야 할 포인트

- `POST /api/v1/bid/distribution` — 스키마 변경이 응답에 영향 없어야 한다(신규 컬럼은 아직 엔진에서 미사용)
- `pytest` — 모델 변경이 기존 테스트를 깨지 않는지
- DB 쿼리로 위 검증 표 재현 가능

## 알려진 미해결 사항

1. **offset 좌표계가 A값 유무를 섞고 있다.** `app/engine/distribution.py`의 `offset = bid_rate − lower_limit_rate`는
   A값 공고(82%)와 비A값 공고를 한 히스토그램에 넣는다. 분리하거나 A값을 역산해 정규화해야 한다.
2. **`notice_title` 미적재 431건.** `data/downloads/` 밖의 다른 소스로 들어온 행(`g2b_code` NULL 431건과 동일 집합).
3. **`adjustment_rate` 이름이 내용과 다르다.** 기존 코드 의존이 있어 건드리지 않고 `preprice_rate`를 추가하는 쪽을 택했다.

## 분석 중 확인된 사실 (T-011 범위 밖이지만 다음 작업에 직결)

낙찰자는 낙찰하한가 바로 위에 붙는다 — `(1순위투찰금액 − 낙찰하한가)/낙찰하한가`의 p50 = **+0.0157%**.
기초금액 1억이면 1.6만 원. 게임 전체가 하한선 위 0.05%p 창문 안에 압축돼 있고 거기 공고당 약 10개사가 있다.

**참여자 수 기준 기대 낙찰률 (깨끗한 표본 12,049건):**

```
E[1/N] = 2.510%     ← 전 공고에 투찰하는 평범한 업체의 기대 낙찰률
  ≤1억      3.261%
  1억~3억    2.674%
  3억~50억   1.371%   ← 최악 구간, 전체의 27%
  50억~     2.615%
```

주의: `1/E[N]`(=0.258%)은 **잘못된 기준**이다. 참여자 수 분포가 극단적으로 왜곡돼 있어
(p5=10, p50=108, p95=1,397) 두 값이 10배 차이 난다.

→ **현재 낙찰률 0.3~0.4%는 어느 구간의 `E[1/N]`보다도 6~8배 낮다.**
공고 선택으로 설명되는 폭은 1.37%~3.26%(2.4배)뿐이므로, 나머지 격차는 다른 데서 온다.
원인 후보: (a) 대형 공고 편중, (b) 투찰가가 하한선에서 멀다, (c) 적격심사 탈락.
**이 격차의 원인 규명이 다음 우선순위다** — 자사 투찰 기록이 필요하고 현재 DB엔 없다.
