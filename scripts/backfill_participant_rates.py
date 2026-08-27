"""
bid_participants.base_rate / vs_lower_limit 백필.

두 컬럼은 54acb1bf74ff 마이그레이션으로 자리는 만들어졌지만 값이 비어 있다.
원본 xls 를 다시 파싱할 필요는 없다 — 이미 DB 에 있는 값으로 계산된다:

    base_rate      = bid_amount / bids_history.base_price
    vs_lower_limit = bid_rate − bids_history.lower_limit_rate

(참여자 원본 xls 는 구글드라이브에 539개만 남아 있고 DB 엔 12,000여 공고분이
 들어 있어 재파싱 자체가 불가능하다. 계산이 유일한 경로다.)

사용법:
    python scripts/backfill_participant_rates.py
    python scripts/backfill_participant_rates.py --dry-run
"""

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gonggong.db"

# base_rate 정상 범위. 투찰금액/기초금액 이므로 0.5~1.5 를 벗어나면 금액 자리수가
# 깨진 행이다 (crud_distribution._RATE_MIN 과 같은 취지).
_RATE_MIN, _RATE_MAX = 0.5, 1.5


def main() -> int:
    ap = argparse.ArgumentParser(description="bid_participants 비율 컬럼 백필")
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 대상 건수만 출력")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB 없음: {DB_PATH}")
        return 1

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    total = cur.execute("SELECT COUNT(*) FROM bid_participants").fetchone()[0]
    before = cur.execute(
        "SELECT COUNT(*) FROM bid_participants WHERE base_rate IS NOT NULL"
    ).fetchone()[0]
    print(f"bid_participants 총 {total:,}행 / base_rate 기적재 {before:,}행")

    if args.dry_run:
        n = cur.execute(f"""
            SELECT COUNT(*) FROM bid_participants p
            JOIN bids_history b ON p.project_id = b.project_id
            WHERE b.base_price > 0
              AND p.bid_amount * 1.0 / b.base_price BETWEEN {_RATE_MIN} AND {_RATE_MAX}
        """).fetchone()[0]
        print(f"[dry-run] 갱신 대상 {n:,}행")
        return 0

    print("base_rate 계산 중...")
    cur.execute(f"""
        UPDATE bid_participants AS p
        SET base_rate = (
            SELECT p.bid_amount * 1.0 / b.base_price
            FROM bids_history b
            WHERE b.project_id = p.project_id AND b.base_price > 0
        )
        WHERE EXISTS (
            SELECT 1 FROM bids_history b
            WHERE b.project_id = p.project_id
              AND b.base_price > 0
              AND p.bid_amount * 1.0 / b.base_price BETWEEN {_RATE_MIN} AND {_RATE_MAX}
        )
    """)
    print(f"  → {cur.rowcount:,}행")

    print("vs_lower_limit 계산 중...")
    cur.execute("""
        UPDATE bid_participants AS p
        SET vs_lower_limit = (
            SELECT p.bid_rate - b.lower_limit_rate
            FROM bids_history b
            WHERE b.project_id = p.project_id
        )
        WHERE EXISTS (
            SELECT 1 FROM bids_history b
            WHERE b.project_id = p.project_id AND b.lower_limit_rate IS NOT NULL
        )
    """)
    print(f"  → {cur.rowcount:,}행")

    con.commit()

    after_br = cur.execute(
        "SELECT COUNT(*) FROM bid_participants WHERE base_rate IS NOT NULL"
    ).fetchone()[0]
    after_vl = cur.execute(
        "SELECT COUNT(*) FROM bid_participants WHERE vs_lower_limit IS NOT NULL"
    ).fetchone()[0]
    print(f"완료: base_rate {after_br:,}행 / vs_lower_limit {after_vl:,}행")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
