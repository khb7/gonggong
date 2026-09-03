"""
고정 사정률(c) 백테스트 — 개찰 결과를 기다리지 않고 판단하는 도구.

실제 투찰 결과는 개찰까지 며칠이 걸린다. 그동안 `FIXED_PREPRICE_RATE` 가
맞는 값인지는 **과거 공고에 되돌려 보면** 알 수 있다.

각 과거 공고에 대해:

    내 투찰가 = (기초금액 × c − A값) × 법정하한율 + A값

    유효  ⟺ 내 투찰가 ≥ 실제 낙찰하한가
    낙찰  ⟺ 유효하면서 그 공고의 **유효 최저 투찰금액보다 낮다**

`bid_participants` 에 전 참여자의 투찰금액이 있으므로 "그때 내가 이 값으로
넣었다면 이겼을까" 를 실제로 셀 수 있다.

한계:
  - 내가 한 명 더 들어가는 효과(경쟁자 +1)와, 내 투찰이 남의 선택을 바꾸는
    효과는 반영하지 않는다. 낙찰률을 조금 낙관적으로 본다.
  - 동일가는 추첨이지만 여기서는 패배로 센다(엄격한 부등호). 보수적이다.
  - 낙찰자 불변식이 깨진 공고는 하한가를 못 믿으므로 제외한다.

사용법:
  python scripts/backtest_bid_rate.py
  python scripts/backtest_bid_rate.py --by-law     # 국가/지방 계약법별로 나눠 본다
"""

import argparse
import io
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.engine.contract_law import classify

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gonggong.db"

# 훑어볼 c 후보 (%)
SWEEP = [99.5, 99.8, 100.0, 100.05, 100.1, 100.15, 100.2, 100.25,
         100.3, 100.4, 100.5, 100.8, 101.0, 101.5, 102.0]

NOTICE_SQL = """
    SELECT b.project_id, b.client_name, b.base_price, b.a_value,
           b.legal_limit_rate, b.lower_limit_price
    FROM bids_history b
    WHERE b.base_price > 0 AND b.lower_limit_price > 0 AND b.legal_limit_rate > 0
      AND b.preprice_rate IS NOT NULL
      -- 낙찰자가 법정 하한율 아래인 공고는 하한가 자체를 못 믿는다
      AND NOT EXISTS (
        SELECT 1 FROM bid_participants w
        WHERE w.project_id = b.project_id AND w.is_winner
          AND w.bid_rate < b.legal_limit_rate - 0.00002)
"""

# 그 공고에서 실제로 이겨야 했던 상대 = 유효 투찰 중 최저 금액
MIN_VALID_SQL = """
    SELECT p.project_id, MIN(p.bid_amount)
    FROM bid_participants p JOIN bids_history b ON p.project_id = b.project_id
    WHERE p.bid_amount >= b.lower_limit_price
      AND p.bid_rate BETWEEN 0.5 AND 1.05
    GROUP BY p.project_id
"""


def load(con):
    notices = con.execute(NOTICE_SQL).fetchall()
    lowest = dict(con.execute(MIN_VALID_SQL).fetchall())
    rows = []
    for pid, client, base, a, rate, floor in notices:
        low = lowest.get(pid)
        if low is None:
            continue
        rows.append((client or "", int(base), int(a or 0),
                     Decimal(str(rate)), int(floor), int(low)))
    return rows


def simulate(rows, c_pct: float) -> tuple[int, int, int]:
    """(대상, 유효, 낙찰)"""
    c = Decimal(str(c_pct)) / 100
    valid = wins = 0
    for _client, base, a, rate, floor, low in rows:
        my = int((Decimal(base) * c - a) * rate + a)
        if my < floor:
            continue
        valid += 1
        if my < low:
            wins += 1
    return len(rows), valid, wins


def report(label: str, rows: list) -> None:
    if len(rows) < 100:
        print(f"\n[{label}] 표본 {len(rows)}건 — 너무 적어 생략")
        return
    print(f"\n=== {label} — 공고 {len(rows):,}건 ===")
    print(f"{'c(%)':>8} {'유효%':>8} {'낙찰':>7} {'낙찰률':>9}")
    best = None
    for c_pct in SWEEP:
        n, v, w = simulate(rows, c_pct)
        if best is None or w > best[1]:
            best = (c_pct, w)
        print(f"{c_pct:>8.2f} {v/n*100:>7.1f}% {w:>7} {w/n*100:>8.3f}%")
    # 낙찰 건수는 카운트라 오차가 대략 sqrt(N) 이다. 그 안이면 구분되지 않는다.
    tol = int(best[1] ** 0.5)
    plateau = [c for c in SWEEP if simulate(rows, c)[2] >= best[1] - tol]
    print(f"\n  최적 c = {best[0]:.2f}%  (낙찰 {best[1]}건)")
    print(f"  통계적으로 구분되지 않는 범위(±√N={tol}): "
          f"{min(plateau):.2f}% ~ {max(plateau):.2f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--by-law", action="store_true",
                    help="국가계약(±2%) / 지방계약(±3%) 로 나눠 본다")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB_PATH))
    rows = load(con)
    if not rows:
        raise SystemExit("대상 공고가 없다. ETL·백필이 끝났는지 확인할 것.")

    report("전체", rows)

    if args.by_law:
        for law, name in (("national", "국가계약 ±2%"), ("local", "지방계약 ±3%")):
            report(name, [r for r in rows if classify(r[0]) == law])

    print("\n주의: 내가 한 명 더 들어가는 효과와 남의 반응은 반영하지 않았다.")
    print("      낙찰률은 조금 낙관적으로 읽어야 한다. 값끼리의 비교가 목적이다.")


if __name__ == "__main__":
    main()
