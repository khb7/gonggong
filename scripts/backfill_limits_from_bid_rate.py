"""
낙찰자 조정 투찰율로 A값·법정 하한율을 정정한다 (추측 없는 경로).

배경:
  `etl_csv.py` 는 낙찰하한가에서 출발해 **법정 하한율을 후보표로 추측**한 뒤
  그 값으로 A값을 역산한다. 후보 간격이 좁은 구간(`0.87495`/`0.87745` 간격 0.0025)
  에서는 A값이 예정가격의 2%만 넘어도 한 칸 위로 오분류되고, 그만큼 A값이
  과소 산출된다. 낙찰자 불변식 위반(투찰율 < 법정 하한율)의 잔여분 원인이다.

  `bid_participants.bid_rate` 는 참여자 원본의 **조정 투찰율**이라 A값이 이미
  반영돼 있다. 여기서 A를 직접 풀면 추측 단계가 사라진다:

      A     = (낙찰가 − bid_rate × 예정가격) / (1 − bid_rate)
      legal = (낙찰하한가 − A) / (예정가격 − A)        → 규정값에 스냅

  원본 파일이 필요 없다 — `bid_participants` 4.6M행이 이미 DB에 있다.
  (참여자 원본 xls 는 구글드라이브에 539개만 남아 재파싱 불가)

안전장치:
  계산된 legal 이 규정 후보값 근처가 아니거나, 정정 후에도 불변식이 깨지거나,
  A값이 비현실적이면 그 행은 **건드리지 않는다**. 추정으로 덮어쓰지 않는다.

사용법:
  python scripts/backfill_limits_from_bid_rate.py            # dry-run (기본)
  python scripts/backfill_limits_from_bid_rate.py --apply
"""

import argparse
import asyncio
import io
import os
import sys
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.engine.a_value import (
    derive_a_value_from_bid_rate,
    snap_legal_limit_rate,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_TOL = Decimal("0.00002")

# a_value 만 미세하게 달라지는 행은 건드리지 않는다.
# 하한율이 그대로일 때의 실측 차이는 예정가격 대비 p99 = 0.0009% 로 순수 반올림 노이즈다.
# 반면 하한율이 한 칸 어긋난 진짜 오분류는 A값이 예정가격의 8% 이상 움직인다.
_MATERIAL_A_RATIO = Decimal("0.001")   # 0.1%

SELECT_SQL = """
    SELECT b.project_id, w.bid_rate, b.est_price, b.winner_price,
           b.lower_limit_price, b.legal_limit_rate, b.a_value, b.has_a_value
    FROM bid_participants w
    JOIN bids_history b ON w.project_id = b.project_id
    WHERE w.is_winner
      AND b.est_price > 0
      AND b.winner_price > 0
      AND b.lower_limit_price IS NOT NULL
      AND b.lower_limit_price > 0
"""

UPDATE_SQL = """
    UPDATE bids_history
       SET a_value = :a,
           legal_limit_rate = :legal,
           effective_limit_rate = :eff,
           has_a_value = :has_a
     WHERE project_id = :pid
"""


async def run(apply: bool) -> int:
    stats = dict(scanned=0, no_a=0, no_snap=0, still_violates=0,
                 unchanged=0, changed=0, rate_fixed=0)
    changes = []

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text(SELECT_SQL))).mappings().all()

        for r in rows:
            stats["scanned"] += 1
            bid_rate = Decimal(str(r["bid_rate"]))
            est = int(r["est_price"])
            llp = int(r["lower_limit_price"])

            a = derive_a_value_from_bid_rate(est, int(r["winner_price"]), bid_rate)
            if a is None:
                stats["no_a"] += 1
                continue

            legal_raw = (Decimal(llp) - Decimal(a)) / (Decimal(est) - Decimal(a))
            legal = snap_legal_limit_rate(legal_raw)
            if legal is None:
                stats["no_snap"] += 1
                continue

            # 정정 후에도 불변식이 깨지면 신뢰하지 않는다.
            if bid_rate < legal - _TOL:
                stats["still_violates"] += 1
                continue

            cur_legal = Decimal(str(r["legal_limit_rate"])) if r["legal_limit_rate"] is not None else None
            rate_same = cur_legal is not None and abs(cur_legal - legal) < _TOL
            a_delta = abs(a - int(r["a_value"] or 0))
            a_material = Decimal(a_delta) > Decimal(est) * _MATERIAL_A_RATIO

            if rate_same and not a_material:
                stats["unchanged"] += 1
                continue

            stats["changed"] += 1
            if not rate_same:
                stats["rate_fixed"] += 1
            changes.append({
                "pid": r["project_id"],
                "a": a,
                "legal": float(legal),
                "eff": float(Decimal(llp) / Decimal(est)),
                # 태그로 이미 A값 공고로 표시된 행을 역산 실패(0)로 되돌리지 않는다.
                "has_a": 1 if (a > 0 or r["has_a_value"]) else 0,
                "_from": float(cur_legal) if cur_legal is not None else None,
            })

        print(f"대상 낙찰자 행: {stats['scanned']}건")
        print(f"  A값 역산 실패      : {stats['no_a']}")
        print(f"  규정값 스냅 실패    : {stats['no_snap']}")
        print(f"  정정 후에도 위반    : {stats['still_violates']}")
        print(f"  이미 올바름        : {stats['unchanged']}")
        print(f"  정정 대상          : {stats['changed']}  (그중 하한율 자체가 바뀌는 행 {stats['rate_fixed']})")

        if changes:
            from collections import Counter
            pairs = Counter((c["_from"], c["legal"]) for c in changes)
            print("\n  법정 하한율 변경 상위:")
            for (old, new), n in pairs.most_common(8):
                print(f"    {old} → {new}   {n}건")

        if not apply:
            print("\n[dry-run] 변경 없음. 적용하려면 --apply")
            return 0

        for c in changes:
            await session.execute(text(UPDATE_SQL), c)
        await session.commit()
        print(f"\n{stats['changed']}건 적용 완료")

    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 DB 를 갱신한다 (기본: dry-run)")
    args = ap.parse_args()
    asyncio.run(run(args.apply))


if __name__ == "__main__":
    main()
