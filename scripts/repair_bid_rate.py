"""
투찰율(bid_rate) 재계산 정정 (일회성).

`bid_participants.bid_rate` 는 info21c 원본의 `투찰율` 컬럼을 그대로 받아왔다.
원본은 **보통** A값이 반영된 조정값을 주지만, 공고에 따라 그렇지 않다.

    A값 공고 14,579개 중
      전 참여자 행이 재계산과 일치   13,134 (90.1%)
      전 참여자 행이 재계산과 불일치   1,158 ( 7.9%)   ← 원본 컬럼 의미가 다른 공고
      섞임                              287 ( 2.0%)

공고 단위로 뭉치는 것으로 보아 원본 컬럼의 의미가 공고마다 다르다.

어느 쪽이 옳은지는 **낙찰자 불변식**이 판정한다 — 낙찰자의 투찰율은 법정
하한율 이상이어야 한다(미달은 실격이라 낙찰될 수 없다).

    두 값이 갈리는 낙찰자 1,267행에서
      재계산값만 불변식 만족   160
      저장값만 만족              1        →  160:1 로 재계산이 옳다

그래서 예정가격을 아는 행은 전부 `(투찰금액 − A) / (예정가격 − A)` 로 다시
계산해 덮는다. 예정가격을 모르면 판단 근거가 없으므로 건드리지 않는다.

⚠ **분포가 실제로 이동한다.** 전체 참여자의 약 10.8% 가 바뀌므로,
  이 스크립트를 돌린 뒤에는 반드시 사전계산을 다시 만들어야 한다.

      python scripts/build_offset_histogram.py

사용법:
    python scripts/repair_bid_rate.py            # dry-run (기본)
    python scripts/repair_bid_rate.py --apply
"""

import argparse
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.a_value import bid_rate_with_a_value

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gonggong.db"

# 이보다 작은 차이는 원 단위 절사에서 나오는 잔차라 정정 대상이 아니다.
_EPS = Decimal("0.00002")

SELECT_SQL = """
    SELECT p.id, p.project_id, p.bid_rate, p.bid_amount, p.is_winner,
           b.est_price, b.a_value, b.legal_limit_rate
    FROM bid_participants p
    JOIN bids_history b ON b.project_id = p.project_id
    WHERE b.est_price > 0 AND p.bid_amount > 0
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="투찰율 재계산 정정")
    ap.add_argument("--apply", action="store_true", help="실제로 반영 (기본은 dry-run)")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB 없음: {DB_PATH}")

    con = sqlite3.connect(str(DB_PATH))

    changes: list[tuple[float, int]] = []
    scanned = agreed = skipped = 0
    # 불변식이 어떻게 움직이는지 먼저 센다 — 정정의 방향이 맞는지 확인하는 지표다.
    fixed_winners = broke_winners = 0

    for pid_row, project_id, br, amount, is_winner, est, a, legal in con.execute(SELECT_SQL):
        scanned += 1
        new = bid_rate_with_a_value(int(amount), int(est), int(a or 0))
        if new is None:
            skipped += 1
            continue
        old = Decimal(str(br))
        if abs(new - old) < _EPS:
            agreed += 1
            continue

        changes.append((float(new), pid_row))
        if is_winner and legal is not None:
            ll = Decimal(str(legal))
            was_ok = old >= ll - _EPS
            now_ok = new >= ll - _EPS
            if now_ok and not was_ok:
                fixed_winners += 1
            elif was_ok and not now_ok:
                broke_winners += 1

    print(f"스캔          : {scanned:,}행")
    print(f"  원본과 일치 : {agreed:,}  ({agreed / scanned * 100:.1f}%)")
    print(f"  재계산 불가 : {skipped:,}")
    print(f"  정정 대상   : {len(changes):,}  ({len(changes) / scanned * 100:.1f}%)")
    print()
    print(f"낙찰자 불변식 : 회복 {fixed_winners:,}건 / 새로 위반 {broke_winners:,}건")
    if broke_winners > fixed_winners:
        print("  ⚠ 새로 깨지는 쪽이 더 많다. 정정 방향을 다시 확인할 것.")

    if not args.apply:
        print("\n실제 반영하려면 --apply 를 붙여 다시 실행하세요.")
        return

    con.executemany("UPDATE bid_participants SET bid_rate = ? WHERE id = ?", changes)
    con.commit()
    print(f"\n반영 완료: {len(changes):,}행")
    print("다음: python scripts/build_offset_histogram.py  ← 분포가 바뀌었으므로 필수")


if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    main()
