"""
adjustment_rate 컬럼 혼동 정정 (일회성).

`bids_history.adjustment_rate` 는 **낙찰가 / 기초금액** 이다 (중앙 0.883).
사정률(예정가격/기초금액, 중앙 0.999)이 아니다.

215건에 사정률이 들어가 있다 — 전부 `adjustment_rate ≈ 1.0000` 인데 실제
`낙찰가/기초` 는 다르다:

    LPC0176-1        저장 1.0000   실제 낙찰가/기초 = 0.9442
    20240526751-01   저장 1.0000   실제 낙찰가/기초 = 0.6514

같은 컬럼 혼동이 두 군데서 더 나왔다:
  - `bidding.py` 가 이 컬럼을 사정률로 써서 예정가격을 13.1% 낮게 추정했다 (T-015)
  - `get_preprice_rate_sigma()` 가 이 컬럼으로 σ 를 재서 오차 밴드가 틀렸다 (T-034)

낙찰가와 기초금액이 둘 다 있으면 다시 계산한다. 재계산값이 정상 범위
(0.70~1.00) 밖이면 원본 금액 자체가 깨진 것이므로 건드리지 않는다 —
그럴듯한 값으로 덮는 것이 이 오염의 원인이었다.

사용법:
    python scripts/repair_adjustment_rate.py            # dry-run (기본)
    python scripts/repair_adjustment_rate.py --apply
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gonggong.db"

# etl_csv.py 가 적재 시 쓰는 것과 같은 범위. 낙찰은 하한율(0.8 대) 위에서
# 이뤄지고 예정가격을 넘을 수 없다.
_RATE_MIN, _RATE_MAX = 0.70, 1.00

SELECT_SQL = f"""
    SELECT project_id, adjustment_rate, winner_price, base_price
    FROM bids_history
    WHERE adjustment_rate IS NOT NULL
      AND (adjustment_rate <= {_RATE_MIN} OR adjustment_rate >= {_RATE_MAX})
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="adjustment_rate 컬럼 혼동 정정")
    ap.add_argument("--apply", action="store_true", help="실제로 반영 (기본은 dry-run)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB 없음: {DB_PATH}")

    con = sqlite3.connect(str(DB_PATH))
    rows = con.execute(SELECT_SQL).fetchall()

    changes: list[tuple[float, str]] = []
    no_input = out_of_range = 0
    samples: list[tuple[str, float, float]] = []

    for pid, cur, wp, base in rows:
        if not wp or not base or base <= 0:
            no_input += 1
            continue
        new = wp / base
        if not (_RATE_MIN < new < _RATE_MAX):
            out_of_range += 1
            continue
        changes.append((new, pid))
        if len(samples) < 5:
            samples.append((pid, cur, new))

    print(f"범위 이탈      : {len(rows):,}건")
    print(f"  재계산 가능  : {len(changes):,}")
    print(f"  금액 없음    : {no_input:,}  (건드리지 않는다)")
    print(f"  재계산해도 이탈: {out_of_range:,}  (원본 금액이 깨졌다 — 건드리지 않는다)")

    if samples:
        print("\n  샘플:")
        for pid, cur, new in samples:
            print(f"    {pid:<22} {cur:.4f} -> {new:.4f}")

    if not args.apply:
        print("\n실제 반영하려면 --apply 를 붙여 다시 실행하세요.")
        return

    con.executemany(
        "UPDATE bids_history SET adjustment_rate = ? WHERE project_id = ?", changes
    )
    con.commit()

    left = len(con.execute(SELECT_SQL).fetchall())
    print(f"\n반영 완료: {len(changes):,}건. 남은 이탈 {left:,}건 (= 정정 불가분)")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
