# Multi-Agent Dev Loop 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Taskmaster MCP + Dev/Eval 이중 에이전트 루프를 설치하고, 첫 이터레이션(bid_type 필터 버그 수정)을 완주한다.

**Architecture:** Taskmaster MCP가 태스크를 관리하고, Dev 세션이 CLAUDE.md 규칙에 따라 "Why 재검토 → 구현 → handoff" 사이클을 실행한다. 별도 Eval 세션이 Playwright + 직접 API 확인으로 3종 검증 후 eval-report.md를 작성한다. 사람이 리포트를 보고 Taskmaster 우선순위를 조정하면 다음 이터레이션이 시작된다.

**Tech Stack:** task-master-ai (npm), Claude Code MCP, Playwright MCP (기설치), FastAPI, SQLite/PostgreSQL, React

---

## 파일 구조

| 파일 | 액션 | 역할 |
|------|------|------|
| `docs/prd.md` | 생성 | Taskmaster가 태스크 분해에 사용하는 프로젝트 요구사항 문서 |
| `docs/eval-agent-prompt.md` | 생성 | Eval 세션 시작 시 사용하는 역할 정의 + 체크리스트 |
| `eval-handoff.md` | 생성(템플릿) | Dev → Eval 핸드오프 노트 (이터레이션마다 덮어씀) |
| `eval-report.md` | 생성(템플릿) | Eval 결과 리포트 (이터레이션마다 덮어씀) |
| `CLAUDE.md` | 수정 | Dev 세션 시작 시퀀스 규칙 추가 |
| `scripts/etl_participants.py` | 수정 | bid_type / price_method 올바르게 적재하도록 수정 |
| `tasks/` | 생성 | Taskmaster가 자동 관리 (직접 편집 금지) |

---

## Task 1: Taskmaster MCP 설치

**Files:**
- Modify: `.claude/settings.local.json` (MCP 설정)

### Windows 환경에서 task-master-ai 전역 설치 및 MCP 등록

- [ ] **Step 1: npm으로 task-master-ai 전역 설치**

```bash
npm install -g task-master-ai
```

Expected output:
```
added N packages in Xs
```

설치 확인:
```bash
task-master-ai --version
```

Expected: 버전 번호 출력 (예: `0.17.0`)

- [ ] **Step 2: Claude Code에 MCP 서버 등록**

```bash
claude mcp add --scope project task-master-ai -e ANTHROPIC_API_KEY=<your-key> -- npx task-master-ai
```

`<your-key>` 자리에 실제 Anthropic API 키 입력 (`.env`에 있으면 거기서 복사).

Expected output:
```
Added MCP server task-master-ai
```

- [ ] **Step 3: MCP 연결 확인**

```bash
claude mcp list
```

Expected: `task-master-ai` 항목이 `✓ Connected` 상태로 표시.

- [ ] **Step 4: 커밋**

```bash
git add .claude/settings.local.json
git commit -m "chore: Taskmaster MCP 등록"
```

---

## Task 2: PRD 문서 작성

**Files:**
- Create: `docs/prd.md`

Taskmaster가 이 파일을 읽어 태스크를 자동 분해한다. 목표·현황·우선순위가 명확해야 한다.

- [ ] **Step 1: `docs/prd.md` 작성**

아래 내용을 그대로 `docs/prd.md`로 저장한다.

```markdown
# 공공입찰 통계 엔진 — PRD

## 프로젝트 목표

나라장터(G2B) 공공입찰에서 **낙찰률 1% 이상** 달성.
현재 0.3~0.4% → 3배 향상이 목표.

핵심 전략: 사정률 예측이 아닌 **경쟁자 분포 시각화 + 의사결정 지원**.
- offset = bid_rate - lower_limit_rate (낙찰하한율 기준 상대 위치)
- 참여자 분포를 보고 "어디에 투찰하면 낙찰 가능성이 높은가"를 판단

## 현재 상태 (2026-05-31)

### 완료된 기능
- Distribution Engine: offset 히스토그램 빌드, 내 위치 계산
- API: POST /api/v1/bid/distribution
- 프론트: BidDistribution 페이지 (React Query, 히스토그램 UI)
- ETL: info21c 다운로드 + DB 적재 (44,044건 bid_participants)
- 참여자 수 추정: 정상 동작 (394명 기준 확인됨)

### 현재 버그 (최우선)
- **bid_type 필터 불일치**: bids_history의 bid_type/price_method가 '기타'로 저장됨
  - ETL 스크립트가 해당 컬럼을 채우지 않아 server_default='기타' 적용됨
  - get_offset_distribution 쿼리가 '적격심사'/'복수예비가격'만 필터링
  - 결과: 히스토그램 0건 반환 → 핵심 기능 동작 안 함

### 다음 개선 목표
1. 히스토그램에 낙찰자 집중 구간 강조 표시
2. 내 투찰가 입력 시 실시간 위치 업데이트
3. 발주처별 분포 필터 기능

## 주요 타겟 발주처
- 국방부 (연말 집중)
- 교육청 (연중 높은 빈도)
- 경기도 지자체 (조경·실내건축)

## 기술 제약
- DB: SQLite (로컬) / PostgreSQL (서버)
- 사정률(예정가격)은 무작위에 가까움 (avg≈1.0, std≈0.007) → ML 예측 금지
- 아키텍처 방향: 시장 분포 시각화 + 의사결정 지원 도구 (예언 모델 아님)
```

- [ ] **Step 2: 커밋**

```bash
git add docs/prd.md
git commit -m "docs: Taskmaster용 PRD 작성"
```

---

## Task 3: Taskmaster 초기화 & 태스크 자동 생성

**Files:**
- Create: `tasks/tasks.json` (Taskmaster가 자동 생성)
- Create: `.taskmaster/config.json` (Taskmaster가 자동 생성)

- [ ] **Step 1: Taskmaster 프로젝트 초기화**

Claude Code 세션에서 Taskmaster MCP를 통해 실행:

```
initialize_project 도구 호출:
  projectRoot: <현재 디렉토리 절대 경로>
```

또는 터미널에서:
```bash
npx task-master-ai init
```

Expected: `tasks/tasks.json` 파일과 `.taskmaster/` 디렉토리 생성.

- [ ] **Step 2: PRD 파싱하여 태스크 자동 생성**

Taskmaster MCP `parse_prd` 도구 호출:
```
parse_prd:
  input: docs/prd.md
  numTasks: 10
```

또는 터미널:
```bash
npx task-master-ai parse-prd docs/prd.md --num-tasks 10
```

Expected: `tasks/tasks.json`에 10개 내외의 태스크 생성. 각 태스크에 title, description, priority, dependencies 포함.

- [ ] **Step 3: 생성된 태스크 검토 및 why 필드 보강**

`tasks/tasks.json`을 열어 각 태스크에 `why` 필드가 없으면 추가한다.
형식:
```json
{
  "id": 1,
  "title": "bid_type 필터 버그 수정",
  "description": "ETL 스크립트가 bids_history의 bid_type/price_method를 '기타'로 저장하는 문제 수정",
  "why": "히스토그램이 0건 반환 중 → 핵심 기능 완전 불동작. 이게 해결돼야 다른 개선이 의미 있음",
  "priority": "high",
  "status": "pending",
  "dependencies": []
}
```

- [ ] **Step 4: 커밋**

```bash
git add tasks/ .taskmaster/
git commit -m "chore: Taskmaster 초기화 및 초기 태스크 생성"
```

---

## Task 4: CLAUDE.md Dev 세션 규칙 추가

**Files:**
- Modify: `CLAUDE.md`

Dev 세션이 매번 자동으로 "Why 재검토 → 구현 → handoff" 사이클을 따르도록 CLAUDE.md에 규칙을 추가한다.

- [ ] **Step 1: CLAUDE.md 하단에 아래 섹션 추가**

```markdown
---

## Dev 세션 시작 프로토콜 (필수)

**모든 Dev 세션은 이 순서를 따른다:**

### 1. 다음 태스크 확인
Taskmaster에서 최우선 태스크를 확인한다:
```
get_next_task 도구 호출 (Taskmaster MCP)
```

### 2. Why 재검토 (3가지 질문에 답하고 진행 여부 결정)
1. **지금도 이게 가장 중요한 작업인가?** — 더 급한 버그나 블로커가 생겼는가?
2. **이미 다른 방법으로 해결됐나?** — 이전 이터레이션에서 간접적으로 해결됐는가?
3. **아키텍처 방향과 맞나?** — 분포 기반 의사결정 도구 방향과 일치하는가?
   (절대 금지: 사정률 예측 강화, ML 기반 숫자 추천, 예정가격 예측)

→ **진행**: `set_task_status` in_progress로 변경 후 구현 시작  
→ **스킵**: Taskmaster에 이유 기록 (`update_task`의 notes 필드) 후 다음 태스크로

### 3. 구현 완료 후 handoff 작성
구현이 완료되면 반드시 `eval-handoff.md`를 작성하고 태스크를 done으로 마킹한다.

`eval-handoff.md` 형식:
```markdown
# Handoff — [태스크명] — [날짜]

## 변경한 파일
- `경로/파일명` — 무엇을 바꿨는가

## Eval 에이전트가 확인해야 할 포인트
- 구체적인 엔드포인트 URL, 예상 응답
- 프론트에서 봐야 할 화면/인터랙션

## 알려진 미해결 사항
- 이번에 해결 못한 것 (있으면 기재)
```
```

- [ ] **Step 2: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md에 Dev 세션 시작 프로토콜 추가"
```

---

## Task 5: Eval 에이전트 프롬프트 파일 작성

**Files:**
- Create: `docs/eval-agent-prompt.md`

Eval 세션을 시작할 때 이 파일 내용을 Claude Code에 붙여넣거나, 세션 첫 메시지로 사용한다.

- [ ] **Step 1: `docs/eval-agent-prompt.md` 작성**

```markdown
# Eval 에이전트 — 역할 정의 및 체크리스트

## 역할

나는 이 공공입찰 시스템의 **실제 사용자 (투찰 담당자)** 입장에서 평가한다.  
개발자의 구현 의도가 아닌, **실제 동작과 사용성**을 기준으로 판단한다.

## 평가 시작 전 준비

1. `eval-handoff.md` 읽기 → 이번 이터레이션에서 무엇을 바꿨는지 파악
2. `git diff HEAD~1 -- <변경된 파일들>` → 코드 변경 내용 확인
3. 백엔드 서버 실행 중인지 확인: `curl http://localhost:8000/health`

## 평가 3종 체크리스트

### A. 기능 동작 검증 (Playwright 사용)

Playwright MCP로 브라우저를 열고 직접 확인한다.

```
browser_navigate: http://localhost:5173  (또는 프론트 포트)
```

체크 항목:
- [ ] 페이지 로드 오류 없음
- [ ] Distribution 페이지 진입 가능
- [ ] 히스토그램에 막대가 표시됨 (0건이면 FAIL)
- [ ] API 직접 호출 확인:
      `curl -X POST http://localhost:8000/api/v1/bid/distribution \
        -H "Content-Type: application/json" \
        -d '{"base_price": 100000000, "lower_limit_rate": 0.87745, "client_name": "테스트", "region": "서울", "project_type": "실내건축"}'`
- [ ] 응답에 `distribution` 배열이 비어있지 않음
- [ ] `estimated_participants` 값이 0이 아님

### B. UX 평가 (투찰 담당자 관점)

투찰 결정을 내려야 하는 사람 입장에서 화면을 본다.

체크 항목:
- [ ] 히스토그램에서 "경쟁자들이 어디에 몰려있는지" 한눈에 파악되는가?
- [ ] 낙찰자 집중 구간이 시각적으로 구분되는가?
- [ ] 내 투찰가를 입력했을 때 내 위치가 명확히 표시되는가?
- [ ] 화면에 불필요한 정보가 있거나, 필요한 정보가 빠진 것은 없는가?
- [ ] 모바일(375px)에서도 히스토그램이 읽힌다고 생각되는가?

### C. 데이터 품질 검증

API 응답 숫자와 DB 데이터가 일치하는지 확인한다.

```bash
# SQLite 기준 (로컬)
python -c "
import sqlite3
conn = sqlite3.connect('data/gonggong.db')
cur = conn.cursor()
cur.execute('''
  SELECT COUNT(*) FROM bid_participants bp
  JOIN bids_history bh ON bp.project_id = bh.project_id
  WHERE bh.bid_type = '적격심사' AND bh.price_method = '복수예비가격'
''')
print('필터 통과 건수:', cur.fetchone())
conn.close()
"
```

체크 항목:
- [ ] DB 필터 통과 건수 > 0
- [ ] API가 반환한 총 참여자 수 합계 ≈ DB 건수 (±5% 오차 허용)
- [ ] 낙찰자(is_winner=True) 비율이 비현실적이지 않음 (0%~10% 범위)
- [ ] offset 범위가 -5% ~ +5% 사이 (이상치 없음)

## eval-report.md 작성 형식

```markdown
# Eval Report — [태스크명] — [날짜]
## 최종 판정: PASS / FAIL / PARTIAL

## A. 기능 동작
(스크린샷 또는 curl 응답 붙여넣기)
이상 없음 / 문제: ...

## B. UX 평가
(실제 화면 보고 느낀 점)
잘 된 점: ...
개선 필요: ...

## C. 데이터 품질
DB 건수: N건
API 합계: N건
일치 여부: YES / NO (이유: ...)

## 다음 권장 태스크
1. [우선순위 높음] ... — 이유: ...
2. ...
3. ...
```

## 리포트 작성 후

`eval-report.md`를 저장하고 사람에게 알린다.
사람이 리포트를 확인한 후 다음 Dev 이터레이션을 시작한다.
```

- [ ] **Step 2: 커밋**

```bash
git add docs/eval-agent-prompt.md
git commit -m "docs: Eval 에이전트 프롬프트 파일 작성"
```

---

## Task 6: 첫 이터레이션 — bid_type 필터 버그 수정 (Dev 파트)

**Files:**
- Modify: `scripts/etl_participants.py` — bid_type/price_method 적재 로직 추가
- Modify: `app/db/crud_distribution.py` — 필터 완화 (기타도 허용)

이번 버그의 원인: `scripts/etl_participants.py`가 `bids_history`의 `bid_type`/`price_method`를 채우지 않아 `server_default='기타'`가 적용됨. 기존 44,044건 모두 '기타'로 저장됨.

**수정 전략 (2단계):**
1. `crud_distribution.py` 필터를 즉시 완화 → 현재 데이터로 히스토그램 동작
2. `etl_participants.py` 수정 → 향후 적재 시 올바른 값 저장

- [ ] **Step 1: 현재 필터 확인**

```bash
grep -n "TARGET_BID_TYPE\|TARGET_PRICE_METHOD\|where(" app/db/crud_distribution.py
```

Expected: `BidsHistory.bid_type == TARGET_BID_TYPE` 형태의 WHERE 절 확인.

- [ ] **Step 2: crud_distribution.py 필터 완화**

`app/db/crud_distribution.py`의 `get_offset_distribution` 함수에서 필터를 제거하거나 완화한다.

변경 전:
```python
.where(
    BidsHistory.bid_type == TARGET_BID_TYPE,
    BidsHistory.price_method == TARGET_PRICE_METHOD,
)
```

변경 후:
```python
.where(
    or_(
        BidsHistory.bid_type == TARGET_BID_TYPE,
        BidsHistory.bid_type == "기타",
    ),
    or_(
        BidsHistory.price_method == TARGET_PRICE_METHOD,
        BidsHistory.price_method == "기타",
    ),
)
```

`or_`는 파일 상단에 이미 import돼 있음 (`from sqlalchemy import select, func, or_`).

- [ ] **Step 3: 필터 완화 후 API 동작 확인**

서버 실행:
```bash
uvicorn app.main:app --reload
```

API 호출:
```bash
curl -X POST http://localhost:8000/api/v1/bid/distribution \
  -H "Content-Type: application/json" \
  -d "{\"base_price\": 100000000, \"lower_limit_rate\": 0.87745, \"client_name\": \"테스트\", \"region\": \"서울\", \"project_type\": \"실내건축\", \"my_bid_price\": 88000000}"
```

Expected: `distribution` 배열에 데이터 존재, `total_count > 0`.

- [ ] **Step 4: etl_participants.py 수정 — bid_type 적재 추가**

`scripts/etl_participants.py`를 열어 bids_history UPDATE 또는 INSERT 로직에 `bid_type`/`price_method` 설정을 추가한다.

먼저 현재 코드 확인:
```bash
grep -n "bid_type\|price_method\|bids_history" scripts/etl_participants.py | head -20
```

`bid_type`을 설정하는 로직이 없으면 아래 패턴으로 추가 (실제 컬럼명/변수명은 파일 확인 후 맞춤):

```python
# bids_history 레코드 생성/업데이트 시
record = {
    ...기존 필드...,
    "bid_type": "적격심사",       # info21c 데이터는 모두 적격심사
    "price_method": "복수예비가격",  # info21c 데이터는 모두 복수예비가격
}
```

> **주의:** info21c 데이터가 실제로 항상 적격심사+복수예비가격인지 소스 확인 필요.
> 확인 방법: info21c 다운로드 CSV의 컬럼명 또는 ETL 로직 주석 참조.

- [ ] **Step 5: eval-handoff.md 작성**

프로젝트 루트에 `eval-handoff.md` 저장:

```markdown
# Handoff — bid_type 필터 버그 수정 — 2026-05-31

## 변경한 파일
- `app/db/crud_distribution.py` — get_offset_distribution 필터 완화 (기타도 허용)
- `scripts/etl_participants.py` — 향후 적재 시 bid_type/price_method 명시 설정

## Eval 에이전트가 확인해야 할 포인트
- `curl -X POST http://localhost:8000/api/v1/bid/distribution ...` → distribution 배열 비어있지 않아야 함
- 프론트 BidDistribution 페이지 → 히스토그램 막대 렌더링 확인
- DB 쿼리: bid_participants JOIN bids_history 건수 > 0

## 알려진 미해결 사항
- 기존 44,044건의 bid_type/price_method가 여전히 '기타'로 저장됨 (필터 완화로 임시 해결)
- 향후 올바른 값으로 백필(backfill) 필요
```

- [ ] **Step 6: Taskmaster에서 태스크 done 마킹 및 커밋**

```bash
git add app/db/crud_distribution.py scripts/etl_participants.py eval-handoff.md
git commit -m "fix: bid_type 필터 완화 — 히스토그램 0건 반환 버그 수정"
```

Taskmaster에서 태스크 완료 처리:
```
set_task_status: id=1, status=done
```

---

## Task 7: 첫 이터레이션 — Eval 세션 실행

**별도 Claude Code 세션에서 실행.**

- [ ] **Step 1: Eval 세션 시작**

새 Claude Code 세션을 열고 첫 메시지로:
```
docs/eval-agent-prompt.md 파일을 읽고 그 역할로 평가를 시작해줘.
이번 이터레이션 handoff는 eval-handoff.md에 있어.
```

- [ ] **Step 2: Eval 에이전트가 3종 검증 수행**

Eval 에이전트가 `docs/eval-agent-prompt.md`의 체크리스트를 따라 A/B/C 검증 수행.

- [ ] **Step 3: eval-report.md 확인**

Eval 세션이 완료되면 `eval-report.md` 파일 내용 확인.
PASS면 다음 이터레이션 진행. FAIL이면 Dev 세션에서 재수정.

- [ ] **Step 4: Taskmaster 우선순위 조정**

eval-report.md의 "다음 권장 태스크"를 보고 Taskmaster에서 다음 이터레이션 태스크를 선택.

---

## 이터레이션 반복 방법

Task 6~7이 완료되면 이후 사이클은 다음과 같이 반복한다:

```
1. Dev 세션 열기
   → "Dev 세션 시작 프로토콜에 따라 다음 태스크 실행해줘" 입력
   → 에이전트가 Taskmaster에서 태스크 꺼내고 Why 재검토 후 구현

2. 구현 완료 → eval-handoff.md 확인

3. Eval 세션 열기
   → "docs/eval-agent-prompt.md 읽고 eval-handoff.md 기준으로 평가 시작해줘" 입력
   → 에이전트가 3종 검증 후 eval-report.md 작성

4. eval-report.md 읽고 승인 또는 재작업 지시

5. Taskmaster에서 다음 태스크 우선순위 조정

6. 1번으로 반복
```
