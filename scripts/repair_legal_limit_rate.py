"""
legal_limit_rate 계산값 잔재 정정 (일회성).

`legal_limit_rate` 는 **규정값**이어야 한다. 구간·계약법·개정시점마다 정해진
이산값이라, 계산으로 나온 연속값이 들어가 있으면 그 자체가 오염 신호다.

과거 적재분 761건에 `낙찰하한가 / 예정가격` 이 그대로 들어가 있다.
전부 규정값 바로 위(오차 1e-9 수준)라 A값이 실제로 0인 공고이며,
값 자체가 틀린 건 아니지만 **규정값이 아니다.**

    R25BK00832331-000   0.8774500004971474   ← 저장된 값
                        0.87745              ← 규정값

**이미 고쳐진 버그의 잔재다.** 같은 입력을 현재 `split_limit_rates()` 에 넣으면
753/753 이 규정값을 돌려준다. 오염은 2025-12 에서 끊기고 그 이후 적재분에는 없다
(2026-08-29~09-09 신규 165건 중 0건). 그래서 코드 수정 없이 데이터만 고친다.

왜 고쳐야 하나:
  - offset 기준선이 법정 하한율이다. 여기에 계산값이 섞이면 히스토그램 x축이
    공고마다 미세하게 밀린다.
  - `validate_data.py` 의 하한율 고유값 수 점검이 오염을 못 걸러낸다.
  - "규정값이 아닌 값이 들어 있다" 는 신호 자체를 잃는다.

사용법:
    python scripts/repair_legal_limit_rate.py            # dry-run (기본)
    python scripts/repair_legal_limit_rate.py --apply
"""

import argparse
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.a_value import snap_legal_limit_rate

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gonggong.db"

# 규정값에서 이만큼 이상 벗어나 있으면 "계산값이 들어갔다" 고 본다.
# 규정 하한율은 소수점 5자리로 고시되므로 그 아래 자릿수는 계산 잔재다.
_DIRTY_EPS = 1e-6

SELECT_SQL = """
    SELECT project_id, legal_limit_rate, effective_limit_rate, a_value
    FROM bids_history
    WHERE legal_limit_rate IS NOT NULL
      AND ABS(legal_limit_rate * 100000 - ROUND(legal_limit_rate * 100000)) > ?
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="legal_limit_rate 계산값 잔재 정정")
    ap.add_argument("--apply", action="store_true", help="실제로 반영 (기본은 dry-run)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB 없음: {DB_PATH}")

    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute(SELECT_SQL, (_DIRTY_EPS,)).fetchall()

    changes: list[tuple[float, str]] = []
    unresolved: list[tuple[str, float]] = []

    for pid, legal, _eff, _a in rows:
        # 규정값 후보로 스냅한다. 어느 후보와도 멀면 정정하지 않는다 —
        # 모르는 값을 그럴듯한 값으로 덮는 것이 애초에 이 오염의 원인이었다.
        snapped = snap_legal_limit_rate(Decimal(str(legal)))
        if snapped is None:
            unresolved.append((pid, legal))
            continue
        changes.append((float(snapped), pid))

    print(f"오염 대상      : {len(rows):,}건")
    print(f"규정값으로 정정: {len(changes):,}건")
    print(f"판별 불가      : {len(unresolved):,}건  (건드리지 않는다)")

    if unresolved:
        print("\n  판별 불가 목록:")
        for pid, legal in unresolved[:10]:
            print(f"    {pid:<24} {legal!r}")

    if changes:
        print("\n  샘플:")
        seen = con.execute(SELECT_SQL, (_DIRTY_EPS,)).fetchmany(3)
        for (pid, legal, _e, _a), (new, _p) in zip(seen, changes[:3]):
            print(f"    {pid:<24} {legal:.16f} -> {new}")

    if not args.apply:
        print("\n실제 반영하려면 --apply 를 붙여 다시 실행하세요.")
        return

    # lower_limit_rate 는 건드리지 않는다. 그 컬럼은 하위 호환용 실효값이라
    # 계산값이 들어 있는 것이 정상이다 (etl_csv.py 참고).
    con.executemany(
        "UPDATE bids_history SET legal_limit_rate = ? WHERE project_id = ?",
        changes,
    )
    con.commit()

    left = con.execute(
        "SELECT COUNT(*) FROM bids_history WHERE legal_limit_rate IS NOT NULL "
        "AND ABS(legal_limit_rate * 100000 - ROUND(legal_limit_rate * 100000)) > ?",
        (_DIRTY_EPS,),
    ).fetchone()[0]
    print(f"\n반영 완료: {len(changes):,}건. 남은 오염 {left:,}건 (= 판별 불가분)")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
