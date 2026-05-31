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
