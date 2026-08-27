# 프로젝트 진행 현황 (2026-03-16)

> ## ⚠️ 오래된 문서 (마지막 갱신 2026-03-16)
>
> 이 시점 이후로 아키텍처가 바뀌었다 — 사정률 예측 폐기, 분포 기반 의사결정으로 전환,
> A값 파이프라인 도입, 낙찰하한율 정합성 복구. 아래 "완료율 80%" 는 폐기된 설계 기준이다.
>
> 현재 진행 상황은 루트 `tasks.md`, 최근 작업 내역은 루트 `eval-handoff.md` 를 본다.

---

---

## 전체 완료율: 약 80%

---

## ✅ 완료된 작업

### 코어 엔진 (100% 완료)
| 파일 | 내용 |
|------|------|
| `app/engine/statistics.py` | `trimmed_median()`, `mad()`, `confidence_range()` |
| `app/engine/strategy.py` | `select_strategy()`, `select_center_offset()`, `generate_bid_spread()` |
| `app/engine/digit_filter.py` | `apply_digit_filter()` — 블랙리스트 끝자리 회피 |
| `app/engine/calculator.py` | `calculate_single()`, `calculate_bid_spread()` |

### DB 레이어 (100% 완료)
| 파일 | 내용 |
|------|------|
| `app/db/models.py` | `BidsHistory`, `ClientStatistics`, `ProjectBucket` ORM |
| `app/db/crud.py` | 읽기 전용 쿼리 (Fallback용) |
| `app/db/crud_write.py` | `bids_history` UPSERT (INSERT ON CONFLICT DO NOTHING) |
| `app/db/session.py` | AsyncSession 설정 |

### Alembic 마이그레이션 (100% 완료)
| 버전 | 내용 |
|------|------|
| `15711de594d0` | initial schema — 테이블 3개 생성 |
| `a3f9e1c72b08` | `bids_history.project_id` unique constraint 추가 |

### API / 외부 연동 (100% 완료)
| 파일 | 내용 |
|------|------|
| `app/schemas/request.py` | `BidRequest`, `BidOverrides` |
| `app/schemas/response.py` | `BidResponse`, `BidItem` |
| `app/external/g2b_fetcher.py` | `G2BFetcher` (실제) + `MockG2BFetcher` (테스트용) |
| `app/api/v1/bidding.py` | `POST /api/v1/bid/calculate` 엔드포인트 |
| `app/main.py` | FastAPI 앱 진입점 |
| `app/core/config.py` | 환경변수 설정 |
| `app/data/fallback.py` | 계층형 Fallback 로직 (client→region→bucket→global) |

### 데이터 수집 파이프라인 (100% 완료)
| 파일 | 내용 |
|------|------|
| `app/external/g2b_collector.py` | `G2BCollector` — 날짜 범위 일괄 수집, 1주일 단위 분할 |
| `app/jobs/collect.py` | 일별 수집 잡 |
| `scripts/backfill.py` | 과거 데이터 초기 적재 |
| `scripts/daily_collect.py` | 매일 자동 수집 스크립트 |

### 테스트 (100% 완료, **전체 56개 통과**)
| 파일 | 검증 대상 |
|------|---------|
| `tests/test_statistics.py` | trimmed_median, mad 순수 계산 |
| `tests/test_calculator.py` | 투찰가 계산 로직 |
| `tests/test_digit_filter_and_strategy.py` | 끝자리 필터, 전략 선택 |
| `tests/test_g2b_fetcher.py` | G2B API 파싱 (MockG2BFetcher 사용) |
| `tests/test_fallback.py` | Fallback 레벨 선택 |
| `tests/test_api_bidding.py` | 엔드포인트 통합 테스트 |

---

## ⏳ 미완료 / 남은 작업

### 인프라 (사용자가 직접 수행해야 함)

| 단계 | 작업 | 상태 |
|------|------|------|
| 1 | PostgreSQL 설치 + `gonggong` DB 생성 | ❓ 미확인 |
| 2 | `.env` 실제 값 입력 (DB URL + G2B API 키) | ❓ 미확인 |
| 3 | `python -m alembic upgrade head` 실행 | ❓ 미확인 |
| 4 | `python scripts/backfill.py` 로 과거 데이터 적재 | ❌ 미실행 |
| 5 | API 호출로 `fallback_level` 확인 | ❌ 미실행 |
| 6 | Windows 작업 스케줄러 등록 (매일 02:00) | ❌ 미설정 |

> 단계별 상세 가이드: `md/setup_todo.md` 참조

### 선택적 개선 사항

| 항목 | 설명 | 우선순위 |
|------|------|--------|
| `app/jobs/refresh_stats.py` | `client_statistics` 캐시 갱신 잡 | 낮음 |
| G2B API 키 없을 때 fallback 동작 문서화 | - | 낮음 |

---

## 현재 상태 요약

```
코드 구현: 완료 ✅
테스트: 56/56 통과 ✅
DB 마이그레이션 파일: 완료 ✅

bids_history 데이터: 비어있음 ❌
  → fallback이 항상 "none" / predicted_rate: 1.0 반환
  → 실제 예측 기능을 쓰려면 backfill 실행 필요
```

---

## 다음 액션

1. **PostgreSQL + `.env` 설정** → `md/setup_todo.md` 1~2단계
2. **`alembic upgrade head`** 실행
3. **`python scripts/backfill.py --start 20250101 --end 20260314`** 실행 (수 시간 소요)
4. API 호출로 `fallback_level` 확인
