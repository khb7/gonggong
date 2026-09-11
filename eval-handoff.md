# Handoff — T-034 σ 컬럼 교체 / 주말 스킵 / adjustment_rate 정정 — 2026-09-11

## 변경한 파일

- `app/db/crud_distribution.py` — `get_adjustment_rate_sigma` →
  `get_preprice_rate_sigma`. 컬럼을 `preprice_rate` 로, `stddev_samp`(Postgres
  전용) 대신 합·제곱합 집계 + 파이썬 제곱근. 캐시 키도 개명.
- `app/api/v1/distribution.py` — 호출부 개명 반영.
- `app/jobs/collect_window.py` — `pending_ranges` 가 주말을 건너뛴다.
  `max_span` 이 평일 수 기준으로 바뀌었다.
- `scripts/repair_adjustment_rate.py` — 신규, 일회성 (dry-run 기본).
- `tests/test_distribution_crud.py` — σ 테스트 3개 + 캐시 격리 픽스처.
- `tests/test_collect_window.py` — 주말 테스트 3개, 기존 2개 기대값 갱신.
- `tests/test_api_distribution.py` — 모킹 대상 이름 갱신.

## Eval 에이전트가 확인해야 할 포인트

**1. 오차 밴드가 실제로 뜨는가 — 이게 핵심이다**

이 기능은 운영에서 **한 번도 렌더된 적이 없다**. `/distribution` 에서
내 투찰가를 입력하면 화살표에 ±1σ 밴드가 보여야 한다.

```bash
curl -s -X POST https://bid.fp-desk.com/api/v1/bid/distribution   -H 'content-type: application/json' -d '{...my_bid_price 포함...}'   | jq '.rate_sigma, .my_position.offset_low_pct, .my_position.offset_high_pct'
```
셋 다 `null` 이면 회귀다. 기대: `rate_sigma ≈ 0.0071`.

**2. σ 가 사정률에서 나오는가**

```bash
python -m pytest tests/test_distribution_crud.py -q -k "sigma"
```
`adjustment_rate` 를 쓰면 0.02 대가 나온다. 0.0007~0.003 범위여야 한다.

**3. 주말이 수집 후보에서 빠지는가**

```bash
python -m pytest tests/test_collect_window.py -q
python scripts/daily_collect.py --days 14 --headless
```
조회 구간에 토·일만 남았으면 "빈 날짜 없음" 으로 끝나야 한다.
금~월 구간이 둘로 쪼개지면 회귀다.

**4. DB 상태 (2026-09-11)**
```
adjustment_rate 범위 이탈   30 (시작 215)
  평균 0.88928 / 중앙 0.88669   ← 낙찰가/기초이므로 0.88 대가 정상
legal_limit_rate 오염        1
낙찰자 불변식 위반          집계 대상 내 15 (0.10%)
σ (preprice_rate)           0.00712
```

## 알려진 미해결 사항

- **`adjustment_rate` 이름이 계속 사고를 낸다.** 같은 혼동이 세 번 나왔다
  (T-015 bidding.py, T-034 σ, T-034 이 컬럼 자체). `award_rate` 같은 이름으로
  개명하는 게 근본 해결이지만 마이그레이션 범위가 커서 보류.
- **불변식 위반 15건** — 전용 도구가 정정을 거부했다(데이터 자체가 모순).
  엔진이 이미 제외 중. 손대지 않는다.
- **고아 공고 235건** — 참여자 xlsx 전수 스캔(~15분)으로 시기 특정은 가능하다.
  파일에 입찰공고번호가 들어 있고 파일명 앞 6자리가 공고 등록일이다.
- **adjustment_rate 이탈 잔여 30건** — 원본 금액이 깨져 재계산해도 범위 밖.
