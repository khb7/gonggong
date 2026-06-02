# Multi-Agent Dev Loop — 설계 문서
*2026-05-31*

## 목표

공공입찰 통계 엔진 프로젝트를 반복적으로 개선하기 위한 반자동 멀티에이전트 개발 루프.
Dev 에이전트(구현)와 Eval 에이전트(검증)가 역할 분리되어 독립적으로 판단한다.

---

## 아키텍처 개요

```
┌─────────────────────────────────────────────────────┐
│                   Taskmaster MCP                    │
│  tasks/  ← PRD 기반 태스크 목록 (why 포함)           │
└──────────────┬──────────────────────────────────────┘
               │
       ┌───────▼────────┐         ┌──────────────────┐
       │   Dev 세션      │ ──────→ │   Eval 세션       │
       │                │ git diff │                  │
       │ 1. 태스크 꺼냄  │  + 파일  │ 1. 변경사항 파악  │
       │ 2. Why 재검토   │         │ 2. 기능 검증       │
       │ 3. 구현         │         │ 3. UX 평가        │
       │ 4. 태스크 완료  │         │ 4. 데이터 검증    │
       └────────────────┘         │ 5. 리포트 작성    │
                                  └────────┬─────────┘
                                           │ eval-report.md
                                  ┌────────▼─────────┐
                                  │     사람 (당신)   │
                                  │ 리포트 읽고 승인   │
                                  │ Taskmaster 조정   │
                                  └──────────────────┘
```

**핵심 파일:**
| 파일 | 역할 |
|------|------|
| `tasks/tasks.json` | Taskmaster 태스크 DB |
| `docs/prd.md` | 프로젝트 목표 & 맥락 (Taskmaster 참조) |
| `eval-handoff.md` | Dev → Eval 핸드오프 노트 |
| `eval-report.md` | Eval 세션 결과 리포트 |

---

## Taskmaster 태스크 구조

각 태스크에 `why` 필드가 필수. Taskmaster PRD 기반 자동 분해 기능 활용.

```json
{
  "id": 1,
  "title": "bid_participants 필터 버그 수정",
  "description": "get_offset_distribution 쿼리의 bid_type 필터가 '기타'로 저장된 데이터를 걸러냄",
  "why": "분포 히스토그램이 0건 반환 중 → 핵심 기능 전혀 동작 안 함",
  "acceptance_criteria": [
    "분포 API가 실제 데이터 반환",
    "히스토그램에 막대가 표시됨"
  ],
  "status": "pending",
  "priority": "high"
}
```

---

## Dev 세션 워크플로우

CLAUDE.md에 추가할 규칙으로 매 세션 자동 실행.

### 시작 시퀀스

```
1. taskmaster next          → 최우선 태스크 확인
2. Why 재검토 (3가지 질문):
   - 지금도 이게 가장 중요한 작업인가?
   - 이미 다른 방법으로 해결됐나?
   - 아키텍처 방향(분포 기반 의사결정)과 맞나?
3. 판단:
   - 진행 → in_progress 마킹 후 구현
   - 스킵 → Taskmaster에 이유 기록, 다음 태스크로
4. 구현 완료 후:
   - Taskmaster done 마킹
   - eval-handoff.md 작성
```

### eval-handoff.md 형식

```markdown
# Handoff — [태스크명] — [날짜]
## 변경한 파일
- `app/db/crud_distribution.py` — 필터 완화
- `app/engine/distribution.py` — ...

## 확인해야 할 포인트
- /api/v1/bid/distribution 응답 데이터 건수
- 프론트 히스토그램 렌더링

## 알려진 미해결 사항
- ...
```

---

## Eval 세션 워크플로우

별도 Claude Code 세션. 매번 아래 컨텍스트로 시작.

### 역할 정의

> 이 공공입찰 시스템의 실제 사용자(투찰 담당자) 입장에서 평가한다.
> 개발자의 구현 의도가 아닌, 실제 동작과 사용성을 기준으로 판단한다.

### 평가 3가지

| 유형 | 방법 | 기준 |
|------|------|------|
| **기능 동작** | Playwright 브라우저 자동화 | 버튼 동작, API 응답, 오류 없음 |
| **UX 평가** | 화면 직접 조작 | "투찰 결정 시 이 정보가 도움이 되는가?" |
| **데이터 품질** | API 응답 vs DB 직접 쿼리 | 숫자 일치, 필터 정합성 |

### eval-report.md 형식

```markdown
# Eval Report — [태스크명] — [날짜]
## 결과: PASS / FAIL / PARTIAL

## 기능 동작
(Playwright 결과 또는 API 응답 스크린샷)

## UX 평가
(투찰 담당자 관점 피드백)

## 데이터 품질
(숫자 검증 결과)

## 다음 권장 태스크
1. (우선순위 높음) ...이유...
2. ...
3. ...
```

---

## 이터레이션 사이클

```
[Taskmaster] → [Dev 세션: Why 재검토 → 구현] → eval-handoff.md
                                                      ↓
                                          [Eval 세션: 3종 검증 → 리포트]
                                                      ↓
                                              eval-report.md
                                                      ↓
                                          [사람: 리포트 검토 → Taskmaster 우선순위 조정]
                                                      ↓
                                              (다음 이터레이션)
```

---

## 구현 순서

1. **Taskmaster MCP 설치** — Claude Code MCP 설정에 task-master-ai 추가
2. **PRD 작성** — `docs/prd.md` (프로젝트 목표, 현재 이슈, 우선순위)
3. **초기 태스크 생성** — PRD 기반 Taskmaster 태스크 자동 분해
4. **CLAUDE.md 업데이트** — Dev 세션 시작 시퀀스 규칙 추가
5. **Eval 세션 프롬프트 파일** — `docs/eval-agent-prompt.md` 작성
6. **첫 이터레이션 실행** — bid_participants 필터 버그 (현재 최우선 이슈)
