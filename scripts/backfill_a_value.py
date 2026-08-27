"""
기존 bids_history 행의 법정/실효 낙찰하한율을 분리하고 A값을 역산한다.

배경:
  마이그레이션 d5c7b39a4e10은 기존 행의 legal/effective를 둘 다
  lower_limit_rate로 채워두었다. 그런데 그 값은 소스에 따라 의미가 달랐다.
    - 원본에 낙찰하한가가 있던 행 → A값이 녹아든 '실효' 하한율
    - 없던 행 / G2B 수집분        → A값이 빠진 '법정' 하한율
  즉 effective 쪽은 이미 맞고, legal 쪽만 틀려 있다.

이 스크립트는 실효 하한율에서 법정 하한율을 역추정하고 A값을 되돌린다.

    예정가격 = base_price × adjustment_rate
    A = (실효 − 법정) / (1 − 법정) × 예정가격

원본 파일을 다시 적재할 수 있으면 그쪽(etl_csv.py --upsert)이 항상 더 정확하다.
이 스크립트는 원본이 없는 과거 적재분을 위한 보정 수단이다.

사용법:
  python scripts/backfill_a_value.py            # dry-run (변경 없음)
  python scripts/backfill_a_value.py --apply
"""

import argparse
import asyncio
import os
import sys
from decimal import Decimal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select

from app.db.models import BidsHistory
from app.db.session import AsyncSessionLocal
from app.engine.a_value import derive_a_value, resolve_legal_limit_rate


async def backfill(apply: bool) -> None:
    scanned = 0
    changed = 0
    with_a = 0
    unresolved = 0

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(BidsHistory).where(
                    BidsHistory.a_value == 0,
                    BidsHistory.effective_limit_rate.is_not(None),
                )
            )
        ).scalars().all()

        for row in rows:
            scanned += 1
            effective = Decimal(str(row.effective_limit_rate))
            legal = resolve_legal_limit_rate(effective)

            if legal is None:
                unresolved += 1
                continue

            # 예정가격 = 기초금액 × 사정률
            expected_price = int(
                Decimal(row.base_price) * Decimal(str(row.adjustment_rate))
            )
            lower_limit_price = int(Decimal(expected_price) * effective)
            a_value = derive_a_value(expected_price, lower_limit_price, legal)

            if legal == Decimal(str(row.legal_limit_rate or 0)) and a_value == 0:
                continue

            changed += 1
            if a_value > 0:
                with_a += 1

            if apply:
                row.legal_limit_rate = legal
                row.a_value = a_value
                row.has_a_value = row.has_a_value or a_value > 0

        if apply:
            await session.commit()

    mode = "적용" if apply else "DRY-RUN (변경 없음)"
    print(f"[{mode}]")
    print(f"  스캔      : {scanned:,}건")
    print(f"  갱신 대상 : {changed:,}건")
    print(f"  A값 발견  : {with_a:,}건")
    print(f"  하한율 판별 실패: {unresolved:,}건")
    if not apply and changed:
        print("\n  실제 반영하려면 --apply 를 붙여 다시 실행하세요.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="bids_history 법정/실효 하한율 분리 + A값 역산 백필"
    )
    parser.add_argument(
        "--apply", action="store_true", help="실제로 DB에 반영 (기본은 dry-run)"
    )
    args = parser.parse_args()
    asyncio.run(backfill(apply=args.apply))


if __name__ == "__main__":
    main()
