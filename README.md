# 공공입찰 통계 엔진

나라장터(G2B) 공공입찰 이력과 참여자 데이터를 분석해 투찰가 계산과 경쟁자 분포 확인을 지원하는 개발용 웹 애플리케이션입니다. 과거 입찰 데이터를 발주처·지역·공종·금액 구간으로 나누어 통계를 만들고, 결과를 FastAPI API와 React 대시보드로 제공합니다.

이 프로젝트의 분석 결과는 입찰 의사결정을 돕기 위한 참고 자료이며, 낙찰 또는 특정 가격을 보장하지 않습니다.

## 주요 기능

- 공고 번호와 선택적 수동 입력값으로 투찰가 계산 (`POST /api/v1/bid/calculate`)
- 과거 참여자의 낙찰하한율 대비 오프셋 분포와 내 투찰가 위치 분석 (`POST /api/v1/bid/distribution`)
- 전체·발주처·지역·사정률 통계 조회
- CSV 가져오기 및 Info21c 형식 데이터의 ETL 적재
- G2B API 기반 백필과 일일 수집 스케줄러 상태 조회
- React 기반 계산, 분포 분석, 통계, 데이터 수집 화면

## 기술 구성

| 영역 | 구성 | 역할 |
| --- | --- | --- |
| 백엔드 | Python, FastAPI | API, 데이터 수집 작업, 통계·계산 로직 |
| 데이터 계층 | SQLAlchemy, Alembic | 비동기 DB 접근과 스키마 마이그레이션 |
| 데이터베이스 | PostgreSQL 또는 SQLite | 입찰 이력, 참여자, 통계용 데이터 저장 |
| 프론트엔드 | React, TypeScript, Vite | 분석·통계 대시보드 |
| 검증 | pytest, Vitest, ESLint | 백엔드·프론트엔드 품질 확인 |

주요 디렉터리:

```text
app/        FastAPI 애플리케이션, 계산 엔진, DB 모델, 외부 연동, 작업 스케줄러
alembic/    DB 마이그레이션
frontend/   React/Vite 웹 애플리케이션
scripts/    CSV ETL, 수집, 데이터 점검·분석 스크립트
data/       로컬 데이터 파일 저장 위치(버전 관리 제외)
tests/      백엔드 테스트
docs/       제품 요구사항, 설계, 작업 계획 등
```

## 빠른 시작

### 1. 백엔드 환경 준비

PowerShell에서 가상 환경을 만들고 Python 의존성을 설치합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`.env.example`을 복사해 `.env`를 만듭니다.

```powershell
Copy-Item .env.example .env
```

로컬에서 PostgreSQL 없이 시작하려면 `.env`의 `DATABASE_URL`을 다음처럼 SQLite URL로 바꿀 수 있습니다.

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./gonggong.db
G2B_API_KEY=
```

`G2B_API_KEY`가 비어 있으면 API는 실제 나라장터 대신 `MockG2BFetcher`를 사용합니다. 실제 G2B 조회·백필을 사용하려면 발급받은 키를 `.env`에 설정하세요. 기본 `.env.example`은 PostgreSQL URL을 사용하므로 PostgreSQL을 선택한 경우에는 별도로 `asyncpg` 드라이버도 설치해야 합니다.

```powershell
pip install asyncpg
```

### 2. 데이터베이스 초기화 및 백엔드 실행

```powershell
alembic upgrade head
python -m uvicorn app.main:app --reload
```

서버는 기본적으로 `http://127.0.0.1:8000`에서 실행됩니다. 실행 중인 서버의 대화형 API 명세는 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)에서 확인할 수 있습니다.

### 3. 프론트엔드 실행

별도 PowerShell 창에서 실행합니다.

```powershell
Set-Location frontend
npm install
npm run dev
```

Vite가 표시하는 로컬 주소(기본값 `http://localhost:5173`)를 브라우저에서 엽니다.

## API 및 화면

### 주요 API

| 경로 | 목적 |
| --- | --- |
| `GET /health` | 서버 상태 확인 |
| `POST /api/v1/bid/calculate` | 공고 정보와 이력 통계를 이용한 투찰가 계산 |
| `POST /api/v1/bid/distribution` | 경쟁자 오프셋 분포, 추정 참여자 수, 내 투찰가 위치 조회 |
| `GET /api/v1/stats/overview` | 전체 데이터 현황 조회 |
| `GET /api/v1/stats/clients` | 발주처별 집계 조회 |
| `GET /api/v1/stats/regions` | 지역별 집계 조회 |
| `GET /api/v1/stats/distribution` | 사정률 히스토그램 조회 |
| `GET`/`POST /api/v1/stats/backfill` | G2B 백필 상태 조회 및 실행 요청 |
| `GET /api/v1/stats/scheduler` | 일일 수집 스케줄러 상태 조회 |
| `GET`/`POST /api/v1/admin/*` | 관리용 CSV 가져오기 화면 및 API |

요청·응답 필드와 유효성 검증 규칙은 실행 중인 FastAPI의 `/docs`를 기준으로 확인하세요.

### 프론트엔드 경로

| 경로 | 화면 |
| --- | --- |
| `/` | 투찰가 계산 |
| `/bid-distribution` | 경쟁자 분포 분석 |
| `/overview` | 데이터 개요 |
| `/clients` | 발주처 통계 |
| `/distribution` | 사정률 분포 |
| `/collection` | 데이터 수집·백필 상태 |

백엔드에서 `frontend/dist`가 존재하면 빌드 결과를 정적으로 제공하므로, 배포 전에는 프론트엔드에서 `npm run build`를 실행하세요.

## 데이터 흐름

```text
Info21c/CSV 또는 G2B 수집
        ↓
scripts/의 ETL·수집 작업
        ↓
입찰 이력 및 참여자 데이터베이스 적재
        ↓
통계·분포·계산 API
        ↓
React 대시보드 및 API 클라이언트
```

CSV 적재에는 다음 스크립트를 사용합니다. `--upsert`를 지정하면 기존 레코드도 업데이트 대상으로 처리합니다.

```powershell
python scripts/etl_csv.py --file <다운로드한-CSV-경로>
python scripts/etl_csv.py --file <다운로드한-CSV-경로> --upsert
```

Info21c 기반 월별 백필 도구는 `scripts/backfill_info21c.py`에 있습니다. 이 도구는 외부 서비스 접근 정보가 필요하므로, 자격 증명은 명령줄이나 저장소가 아니라 안전한 로컬 환경에서 관리하세요.

## 테스트와 품질 확인

백엔드 테스트는 저장소 루트에서 실행합니다.

```powershell
pytest
```

프론트엔드 검사와 빌드는 `frontend/`에서 실행합니다.

```powershell
npm run lint
npm test
npm run build
```

## 운영 시 유의사항

- 실제 수집과 백필은 유효한 `G2B_API_KEY`, 접근 가능한 데이터베이스, 외부 API 연결이 필요합니다.
- API 키, 서비스 계정, 다운로드 자격 증명, 개인 키는 `.env` 등 로컬 비밀 저장소에만 두고 Git에 추가하지 마세요.
- 개발 서버는 G2B API 키가 없을 때 Mock fetcher로 동작하므로, 실제 데이터 품질이나 수집 동작을 검증하려면 운영용 설정이 필요합니다.
- `scripts/daily_collect.py`는 현재 Windows 환경에서 직접 실행 시 문자열 경로 파싱 오류가 발생할 수 있습니다. 일일 수집을 운영에 연결하기 전에 해당 스크립트의 실행 여부를 별도로 확인하세요.
