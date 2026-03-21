# 데이터 수집 시작 전 준비 사항

코드 구현은 완료. 아래 순서대로 실행하면 실제 데이터 수집이 가능해진다.

---

## 1단계. PostgreSQL 설치 & DB 생성

### PostgreSQL 설치 (아직 없다면)

https://www.postgresql.org/download/windows/ 에서 설치.
설치 시 설정한 유저명/비밀번호를 기억해둔다.

### DB 생성

설치 후 psql 또는 pgAdmin에서:
```sql
CREATE DATABASE gonggong;
```

---

## 2단계. `.env` 실제 값으로 수정

`C:\Users\onebe\gonggong\.env` 파일을 열어서 아래처럼 수정:

```
DATABASE_URL=postgresql+asyncpg://유저명:비밀번호@localhost:5432/gonggong
G2B_API_KEY=공공데이터포털에서_발급받은_키
```

### G2B API 키 발급

1. https://www.data.go.kr 접속 → 로그인
2. 검색: `나라장터 차세대 낙찰정보`
3. `getDataSetOpnStdScsbidInfo` 포함된 서비스 신청
4. 마이페이지 → 서비스키 확인 → `.env`에 붙여넣기

⚠ API 키는 URL 인코딩 전 원문을 그대로 사용. `%` 같은 특수문자 그대로 복붙.

---

## 3단계. DB 마이그레이션 실행

```bash
cd C:\Users\onebe\gonggong
python -m alembic upgrade head
```

성공 시 출력:
```
Running upgrade  -> 15711de594d0, initial schema
Running upgrade 15711de594d0 -> a3f9e1c72b08, add project_id unique constraint
```

테이블이 생성됐는지 확인:
```sql
-- psql에서
\dt
-- bids_history, client_statistics, project_bucket 3개가 보여야 함
```

---

## 4단계. 백필 실행 (과거 데이터 적재)

```bash
cd C:\Users\onebe\gonggong
python scripts/backfill.py --start 20250101 --end 20260314
```

- 1년치 기준 수십만 건, 수 시간 소요 예상
- 중간에 끊겨도 괜찮음 — 재실행 시 이미 수집된 건 자동 스킵 (ON CONFLICT DO NOTHING)
- 최소 3개월치는 있어야 fallback이 `"none"` 에서 벗어남

진행 상황 확인 (psql):
```sql
SELECT COUNT(*) FROM bids_history;
SELECT fallback_level, COUNT(*) FROM ... -- API 호출로 확인
```

---

## 5단계. 수집 잘 됐는지 API로 확인

서버 실행:
```bash
python -m uvicorn app.main:app --reload
```

테스트 요청:
```bash
curl -X POST http://localhost:8000/api/v1/bid/calculate \
  -H "Content-Type: application/json" \
  -d '{"bid_notice_id": "실제공고번호"}'
```

응답에서 `fallback_level`이 `"none"`이 아니라 `"client"` / `"region"` / `"type_bucket"` 이면 성공.

---

## 6단계. 일별 자동 수집 설정 (Windows 작업 스케줄러)

백필 완료 후 매일 새 낙찰결과가 자동으로 쌓이도록 설정.

1. 시작 메뉴 → `작업 스케줄러` 검색 → 열기
2. 오른쪽 패널 → `기본 작업 만들기`
3. 설정:
   - 이름: `공공입찰 일별 수집`
   - 트리거: `매일` → 시작: `새벽 02:00`
   - 동작: `프로그램 시작`
     - 프로그램: `python`
     - 인수: `C:\Users\onebe\gonggong\scripts\daily_collect.py`
     - 시작 위치: `C:\Users\onebe\gonggong`
4. 저장 후 `지금 실행`으로 테스트

---

## 요약

| 단계 | 명령 / 작업 | 완료 조건 |
|------|------------|---------|
| 1 | PostgreSQL 설치 + `gonggong` DB 생성 | psql 접속 가능 |
| 2 | `.env` 수정 (DB URL + G2B API 키) | - |
| 3 | `python -m alembic upgrade head` | 테이블 3개 생성 확인 |
| 4 | `python scripts/backfill.py --start 20250101 --end 20260314` | `bids_history` 건수 확인 |
| 5 | API 호출로 `fallback_level` 확인 | `"none"` 이 아님 |
| 6 | Windows 작업 스케줄러 등록 | 매일 02:00 자동 실행 |
