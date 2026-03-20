# GUI 개발 계획

## 구조 결정

### 기술 스택
| 구분 | 결정 | 이유 |
|------|------|------|
| Frontend | React (Loveable 초안) | 사용자 선호 |
| Backend | FastAPI (기존 유지) | 이미 구현됨 |
| 배포 방식 | FastAPI가 React 빌드 정적 파일 서빙 | 별도 서버 불필요, 단일 프로세스 |
| 실행 | `start.bat` 더블클릭 → 서버 시작 + 브라우저 자동 오픈 | 비개발자도 사용 가능 |

### 배포 구조
```
다른 PC에서 실행 시:
1. gonggong 폴더 복사
2. PostgreSQL 설치
3. .env 설정 (DB URL + G2B API 키)
4. start.bat 실행
5. 브라우저 자동으로 열림
```

---

## 화면 구성 (대시보드)

### 1. 투찰가 계산 (메인)
- 공고번호 입력 → 계산 버튼
- Override 옵션 (기초금액, 하한율, 참여업체수 직접 입력)
- 결과 카드 3개: Aggressive / Normal / Safe
  - 투찰가 (원), 투찰율 (%), digit filter 적용 여부
- 사용된 fallback_level 표시 (신뢰도 표시)
- 사용된 통계 정보: predicted_rate, 샘플 수, 전략

### 2. 데이터 현황
- bids_history 총 건수
- 수집 기간 (최초 ~ 최근 날짜)
- 최근 수집일
- fallback_level 분포 (pie chart): client / region / type_bucket / global / none 비율

### 3. 발주처 통계
- 발주처별 낙찰 건수 top 20 (bar chart)
- 발주처별 평균 사정률
- 클릭 시 해당 발주처 상세 (사정률 분포)

### 4. 지역별 통계
- 지역별 낙찰 건수 / 평균 사정률

### 5. 사정률 분포
- 전체 사정률 히스토그램
- 공종별 필터 (실내건축 / 조경 / 전체)

---

## 백엔드 추가 API (현재 없는 것들)

현재 `POST /api/v1/bid/calculate` 1개만 있음. 대시보드를 위해 추가 필요:

| 엔드포인트 | 용도 |
|-----------|------|
| `GET /api/v1/stats/overview` | 전체 현황 (총 건수, 수집 기간 등) |
| `GET /api/v1/stats/clients` | 발주처별 통계 |
| `GET /api/v1/stats/regions` | 지역별 통계 |
| `GET /api/v1/stats/distribution` | 사정률 분포 데이터 |

---

## 개발 순서

1. **백엔드 통계 API 추가** (FastAPI)
2. **Loveable로 React 초안 생성** (사용자가 진행)
3. **React → FastAPI 연동** (API 호출 연결)
4. **FastAPI에서 React 빌드 파일 서빙** (단일 프로세스화)
5. **start.bat 작성** (배포용)

---

## 결정된 사항
- OS: Windows 전용 → Inno Setup (.exe installer)
- DB: PostgreSQL dump → restore 방식
- Installer 포함 범위: Python + PostgreSQL + 앱 코드 + DB dump
- 수집: 각 PC가 자체 수집
- 로그인: 불필요 (로컬 전용)

## 미결 사항
없음 — 개발 시작 가능
