# Handoff — T-032 수집 파이프라인 반쪽 실행 수정 — 2026-09-10

## 변경한 파일

- `scripts/info21c_downloader.py` — 페이지네이션. `goto_next_page()` 신설,
  `set_search_filters()` 가 행 수 반환, `run_download()` 가 `list[Path]` 반환,
  `export_csv(page_num=)` 로 2페이지부터 `_p2` 접미사. `PAGE_SIZE` 상수화.
- `scripts/daily_collect.py` — `collect_notices()` (목록 leg, 참여자보다 먼저),
  `count_orphans()` + 실행 전후 비교 → 늘었으면 exit 1. 모듈 docstring 재작성.
- `CLAUDE.md` — 경로 A 를 daily_collect 중심으로 재작성, 새는 두 방식 명시.
- `docs/deployment.md` — 9절 재작성 (주 1회 수동 루틴), 사전계산 수치 갱신
  (159 스코프/25,000 bin → 19 스코프/9,297 bin, 실측).

## Eval 에이전트가 확인해야 할 포인트

**1. 페이지네이션이 실제로 넘어가는가** — 100건을 넘는 창으로 확인한다.

```bash
python scripts/info21c_downloader.py --start 20260829 --end 20260909 --type 0002 --headless
```

기대 출력:
```
검색 완료 (100건 로드됨)
[3/4] 엑셀 내보내기 중... (1페이지)
  → 2페이지 (23건)
[3/4] 엑셀 내보내기 중... (2페이지)
=== 다운로드 완료 (2개 파일) ===
```
파일이 1개만 나오면 회귀다.

**2. daily_collect 가 두 leg 를 순서대로 도는가**

```bash
python scripts/daily_collect.py --days 14 --headless
```

기대: 구간마다 `[목록] N개 파일 → 신규 x건 / 기존 y건` 이 **참여자 로그보다 먼저**
찍히고, 끝에 `고아 공고: N → M (+0)` 과 종료 코드 0.

**3. 고아 검사가 실제로 실패로 이어지는가** — 목록 leg 를 일부러 건너뛰면
exit 1 이 나야 한다. `collect_notices` 호출을 주석 처리하고 미수집 구간에서 실행.

**4. DB 상태** (2026-09-10 배포 완료)
```
공고 16,307 / 참여자 5,942,388 / 기간 2023-12-22 ~ 2026-09-09
offset_histogram 9,297 / offset_scope_stat 19
고아 235
```

**운영 확인** (`https://bid.fp-desk.com`): 분포 요청 정상, fallback client
(경기도 평택시, 표본 489 공고 / 71,688 참여자), 응답 2.7초, RAM 사용 239MB.

## 알려진 미해결 사항

- **고아 235건.** 시기 특정 불가 (옛 로그 포맷). 전체의 1.4%.
  조인에서 빠질 뿐이라 데이터 오염은 아니다.
- **주말이 매번 미수집으로 잡힌다.** 개찰이 없어 참여자 날짜에 안 남으므로
  `pending_ranges` 가 계속 후보로 올린다. 실행마다 몇 분 낭비. 동작은 정상.
- **`validate_data.py` WARN 2건** — 낙찰자 불변식 위반 403건(2.5%),
  adjustment_rate 범위 이탈 215건. 연도별로 고르게 퍼져 있어 특정 ETL 회귀가
  아니라 꾸준한 파싱 실패율이다. 별건.
- **`legal_limit_rate` 부동소수점 오염 761건** (`0.8774500000000001` 형태).
  "모든 비율은 Decimal" 규칙이 ETL 어딘가에서 새고 있다. 별건.
