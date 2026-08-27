# Statistical Engine 구현 계획

> ## ⛔ 폐기된 문서 (2026-08-27)
>
> `사정률 예측 → 투찰가 산출` 파이프라인 구현 계획이다. 그 파이프라인이 폐기됐다.
> 사정률은 복수예비가격 구조상 예측 대상이 아니다.
> 근거: [2026-05-29-distribution-engine-analysis.md](../design/2026-05-29-distribution-engine-analysis.md)
>
> - `Aggressive: -MAD` (113·274행) — 음수 offset 은 **하한가 미달 = 실격**이다
> - 투찰 공식에 A값이 없다
>
> 현재 주 경로는 `POST /bid/distribution` 이다.
> 대신 볼 문서: 루트 `CLAUDE.md`, [공공입찰_제도_가이드.md](../reference/공공입찰_제도_가이드.md)

---

통계 기반 투찰가 계산 엔진을 Python + PostgreSQL + FastAPI로 구현한다.  
핵심은 `사정률 예측 → 투찰가 산출` 파이프라인이며, DB 없이도 단위 테스트가 가능한 구조로 설계한다.

---

## Proposed Changes

### Phase 1 — 프로젝트 초기 세팅

#### [NEW] `gonggong/requirements.txt`
```
fastapi
uvicorn
sqlalchemy
alembic
asyncpg
pydantic
pydantic-settings
numpy
scipy
python-dotenv
```

#### [NEW] `gonggong/.env.example`
```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/gonggong
```

#### [NEW] `gonggong/app/` 디렉토리 구조 전체 생성
```
app/
├── main.py
├── api/v1/bidding.py
├── engine/
│   ├── statistics.py
│   ├── strategy.py
│   ├── digit_filter.py
│   └── calculator.py
├── external/
│   └── g2b_fetcher.py     # 나라장터 OpenAPI 연동 (외부 통신 격리)
├── data/fallback.py
├── db/
│   ├── models.py
│   ├── crud.py
│   └── session.py
└── schemas/
    ├── request.py
    └── response.py
```

---

### Phase 2 — DB 모델

#### [NEW] `app/db/models.py`

세 가지 테이블을 SQLAlchemy ORM으로 정의한다.

| 테이블 | 역할 |
|---|---|
| `bids_history` | 과거 입찰 결과 (사정률, 하한율, 경쟁자 수 등) |
| `client_statistics` | 발주처별 Trimmed Median / MAD 캐시 |
| `project_bucket` | 금액 구간 정의 (초기 시드 데이터) |

---

### Phase 3 — Statistical Engine 코어 (핵심)

#### [NEW] `app/engine/statistics.py`

```python
# ⚠ 전체 엔진에서 float 대신 Decimal을 일관되게 사용한다.
# 이유: 사정률은 소수점 5~6자리까지 의미를 가지며,
#       float 연산 오차(예: 0.745 → 0.7450000000000001)가
#       digit_filter 등 하위 로직 전체에 전파될 수 있다.
from decimal import Decimal

def trimmed_median(rates: list[Decimal], trim_pct: float = 0.05) -> Decimal:
    """상·하위 trim_pct% 제거 후 중앙값 반환"""

def mad(rates: list[Decimal]) -> Decimal:
    """Median Absolute Deviation 계산"""

def confidence_range(median: Decimal, mad_val: Decimal) -> tuple[Decimal, Decimal]:
    """[Median - MAD, Median + MAD] 신뢰 범위 반환"""
```

#### [NEW] `app/data/fallback.py`

발주처 → 지역 → 공종+버킷 → 전체 순으로 데이터를 조회하는 계층형 Fallback 로직.  
각 레벨은 `sample_size >= 20`을 충족해야 채택한다.

```python
async def get_rates_with_fallback(
    db, client_name, region, project_type, bucket_id
) -> tuple[list[float], str]:
    """(사정률 리스트, 사용된_fallback_레벨) 반환"""
```

#### [NEW] `app/engine/strategy.py`

```python
# Float 정밀도 문제 → Decimal 기반으로 모든 사정률 처리
from decimal import Decimal

def select_offset(participants: int, mad: Decimal) -> tuple[Decimal, str]:
    """
    경쟁자 수 기반 Offset 및 전략명 반환
    - < 50   → Safe      : +MAD
    - 50~299 → Normal    : 0
    - ≥ 300  → Aggressive: -MAD
    """

def generate_bid_spread(
    center: Decimal, step: Decimal = Decimal("0.001"), count: int = 3
) -> list[Decimal]:
    """
    중심 타점(center)을 기준으로 step 간격의 후보 배열 생성.
    예) center=0.87746, step=0.001, count=3
        → [0.87646, 0.87746, 0.87846]
    """
```

#### [NEW] `app/engine/digit_filter.py`

> **Float 오차 방지:** `decimal.Decimal`을 사용하거나 소수점 3자리를 문자열로 추출하여 비교한다.  
> `if rate in {0.745}` 방식은 `0.7450000000000001` 오차로 필터가 뚫릴 수 있으므로 절대 사용 금지.

```python
from decimal import Decimal, ROUND_HALF_UP

# 블랙리스트: 문자열 3자리로 비교
DIGIT_BLACKLIST = {"000", "500", "745", "777"}

def apply_digit_filter(rate: Decimal) -> Decimal:
    """
    소수점 끝 3자리를 문자열로 추출해 블랙리스트와 비교.
    해당 시 +0.001 Shift 후 재귀 검사. 안전한 값 반환.
    예) 0.87745 → '745' 매칭 → 0.87746 반환
    """
    tail = str(rate)[-3:]           # 문자열 슬라이싱으로 float 오차 제거
    if tail in DIGIT_BLACKLIST:
        return apply_digit_filter(rate + Decimal("0.001"))
    return rate
```

#### [NEW] `app/engine/calculator.py`

전략별 중심 offset을 기준으로 `generate_bid_spread`로 다중 타점을 생성하고,
각 후보에 `digit_filter`를 적용한 뒤 원화·비율로 변환하여 리스트로 반환한다.

```python
from decimal import Decimal

def calculate_single(
    base_price: int,
    lower_limit_rate: Decimal,
    predicted_rate: Decimal,
    offset: Decimal,
) -> dict:
    """
    Final Bid Price = base_price × predicted_rate × (lower_limit_rate + offset)
    { rate_pct: float, price_krw: int } 반환
    """

def calculate_bid_spread(
    base_price: int,
    lower_limit_rate: Decimal,
    predicted_rate: Decimal,
    center_offset: Decimal,
    step: Decimal = Decimal("0.001"),
    count: int = 3,
) -> list[dict]:
    """
    Multi-Shot Bid Spread:
    1. center_offset 기준으로 step 간격의 후보 count개 생성
    2. 각 후보에 digit_filter 적용
    3. calculate_single로 원화·비율 계산
    4. [{label, rate_pct, price_krw}, ...] 리스트 반환

    예) predicted_rate=1.0, LLR=0.87745, center=0.0, step=0.001, count=3
        → offsets: [-0.001, 0.000, +0.001]
        → raw rates: [0.87645, 0.87745, 0.87845]
        → digit_filter 적용 후 최종 3개 타점 반환
    """
```

---

### Phase 4 — FastAPI 엔드포인트

#### [NEW] `app/schemas/request.py`

```python
class BidOverrides(BaseModel):
    base_price: int | None = None
    lower_limit_rate: float | None = None
    participants: int | None = None

class BidRequest(BaseModel):
    bid_notice_id: str
    overrides: BidOverrides | None = None
```

#### [NEW] `app/schemas/response.py`

```python
class BidItem(BaseModel):
    label: str       # "Aggressive" | "Normal" | "Safe"
    rate_pct: float
    price_krw: int

class BidResponse(BaseModel):
    bid_notice_id: str
    mode: str        # "auto" | "override"
    overridden_fields: list[str]
    strategy: str
    predicted_rate: float
    bids: list[BidItem]
    digit_filter_applied: bool
    fallback_level: str
```

#### [NEW] `app/external/g2b_fetcher.py`

나라장터 OpenAPI 연동 로직을 외부 통신 레이어로 격리한다.  
Mock 구현체(`MockG2BFetcher`)와 실제 구현체(`G2BFetcher`)를 동일 인터페이스로 교체 가능하게 설계.

```python
class G2BFetcher:
    async def fetch(self, bid_notice_id: str) -> dict:
        """나라장터 API 호출 후 {base_price, client_name, ...} 반환"""

class MockG2BFetcher(G2BFetcher):
    """테스트/장애 대응용 Mock — 실제 API 호출 없이 고정값 반환"""
```

#### [NEW] `app/api/v1/bidding.py`

`POST /api/v1/bid/calculate` 엔드포인트.  
Phase 1에서는 `MockG2BFetcher` 사용, 실제 연동 시 `G2BFetcher`로 교체.

---

## Verification Plan

### Automated Tests

파일: `tests/test_statistics.py`, `tests/test_strategy.py`, `tests/test_calculator.py`

#### 실행 방법
```bash
cd c:\Users\Lenovo\gonggong
pip install -r requirements.txt
pytest tests/ -v
```

#### test_statistics.py 검증 케이스

| 케이스 | 입력 | 기대 출력 |
|---|---|---|
| 정상 Trimmed Median | `[0.99, 1.00, 1.01, 0.50, 1.50]` (5% trim) | `1.00` |
| 전체 같은 값 | `[1.0] * 10` | `1.0` |
| MAD 계산 | `[1.0, 1.01, 0.99, 1.005]` | `≈ 0.005` |

#### test_strategy.py 검증 케이스

| 경쟁자 수 | 기대 전략 | 기대 Offset |
|---|---|---|
| 30 | Safe | `+MAD` |
| 100 | Normal | `0` |
| 350 | Aggressive | `-MAD` |

#### test_calculator.py 검증 케이스

```
base_price = 1,000,000,000
lower_limit_rate = 0.87745
predicted_rate = 1.0000
offset = 0.0

기대값: 1,000,000,000 × 1.0 × (0.87745 + 0.0) = 877,450,000원
```

### Manual Verification (서버 실행 후)

```bash
cd c:\Users\Lenovo\gonggong
uvicorn app.main:app --reload

# Auto-Fetch Mode 테스트 (Mock G2B 데이터 사용)
curl -X POST http://localhost:8000/api/v1/bid/calculate \
  -H "Content-Type: application/json" \
  -d '{"bid_notice_id": "TEST-001"}'

# Override Mode 테스트
curl -X POST http://localhost:8000/api/v1/bid/calculate \
  -H "Content-Type: application/json" \
  -d '{"bid_notice_id": "TEST-001", "overrides": {"base_price": 950000000}}'
```

Swagger UI: `http://localhost:8000/docs` 에서도 확인 가능.
