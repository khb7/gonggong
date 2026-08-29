"""
넓은 스코프의 offset 히스토그램을 미리 계산해 DB 에 저장한다.

배경:
  조회 경로는 참여자 4.5M 행을 SQL 로 집계한다. 메모리는 괜찮지만(RSS 14.6MB)
  스캔 자체가 느리다. 서버(OCI E2.1.Micro, 1 OCPU / RAM 1GB) 실측:

      client      0.6s   ← 충분히 빠르다. 사전계산하지 않는다
      region     22.3s
      global     69.1s

  넓은 스코프는 값이 자주 바뀌지 않으므로 여기서 한 번 계산해 표로 넣는다.
  그러면 서버는 참여자 테이블을 스캔할 일이 없다.

  ⚠ 이 스크립트는 **로컬에서** 돌린다. 결과는 DB 파일에 담겨 서버로 간다.
    서버에서 돌리면 애초에 피하려던 그 스캔을 그대로 하게 된다.

무엇을 계산하나:
      global       1개
      region       지역명마다      (region 컬럼은 '전국,경기' 처럼 복수값이라 분해한다)

  각 스코프마다 히스토그램(offset_histogram)과 공고 수·참여자 수(offset_scope_stat)를
  같이 저장한다. fallback 레벨 채택이 공고 수로 판단되기 때문이다.

사용법:
  python scripts/build_offset_histogram.py            # 전부 다시 만든다
  python scripts/build_offset_histogram.py --only global
"""

import argparse
import asyncio
import io
import os
import sys
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import delete, select, text

from app.db.models import BidsHistory, OffsetHistogram, OffsetScopeStat
from app.db.session import AsyncSessionLocal
from app.db.crud_distribution import (
    count_offset_distribution,
    get_offset_distribution,
    scope_key_for,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

async def _region_names(session) -> list[str]:
    """region 컬럼에서 실제 지역명을 뽑는다.

    '전국,경기' 처럼 복수 값이 들어 있어 그대로 쓰면 안 된다.
    조회 시 `region LIKE '%경기%'` 로 매칭하므로 분해한 단일 지역명이 필요하다.
    """
    rows = await session.execute(
        select(BidsHistory.region).where(BidsHistory.region.is_not(None)).distinct()
    )
    names: set[str] = set()
    for (raw,) in rows:
        for part in str(raw).split(","):
            part = part.strip()
            if part and part != "기타":
                names.add(part)
    return sorted(names)


async def _build_one(session, level: str, key: str, kwargs: dict) -> tuple[int, int]:
    """스코프 하나를 계산해 저장한다. (bin 수, 참여자 수) 반환."""
    bins = await get_offset_distribution(session, **kwargs)
    notices, bids = await count_offset_distribution(session, **kwargs)

    await session.execute(
        delete(OffsetHistogram).where(
            OffsetHistogram.scope_level == level, OffsetHistogram.scope_key == key
        )
    )
    await session.execute(
        delete(OffsetScopeStat).where(
            OffsetScopeStat.scope_level == level, OffsetScopeStat.scope_key == key
        )
    )

    for b in bins:
        session.add(
            OffsetHistogram(
                scope_level=level,
                scope_key=key,
                offset_pct=b["offset_pct"],
                count=b["count"],
                win_count=b["win_count"],
            )
        )
    session.add(
        OffsetScopeStat(scope_level=level, scope_key=key, notices=notices, bids=bids)
    )
    return len(bins), bids


async def run(only: str | None) -> None:
    async with AsyncSessionLocal() as session:
        targets: list[tuple[str, str, dict]] = []

        if only in (None, "global"):
            targets.append(("global", scope_key_for("global", None), {}))

        if only in (None, "region"):
            for name in await _region_names(session):
                targets.append(
                    ("region", scope_key_for("region", name), {"region": name})
                )

        print(f"대상 스코프 {len(targets)}개\n")
        started = time.time()
        total_bins = skipped = 0

        for i, (level, key, kwargs) in enumerate(targets, 1):
            t0 = time.time()
            nbins, bids = await _build_one(session, level, key, kwargs)
            total_bins += nbins
            if nbins == 0:
                skipped += 1
            print(
                f"  [{i:>3}/{len(targets)}] {level:<11} {key[:34]:<36} "
                f"bin {nbins:>4}  참여 {bids:>9,}  {time.time()-t0:>6.1f}s"
            )

        await session.commit()

        print(
            f"\n완료: {len(targets)}개 스코프 / {total_bins:,} bin "
            f"(빈 스코프 {skipped}개) / {time.time()-started:.1f}s"
        )

        size = await session.execute(
            text("SELECT COUNT(*) FROM offset_histogram")
        )
        print(f"offset_histogram 총 행: {size.scalar():,}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only",
        choices=["global", "region"],
        help="특정 레벨만 다시 만든다 (기본: 전부)",
    )
    args = ap.parse_args()
    asyncio.run(run(args.only))


if __name__ == "__main__":
    main()
