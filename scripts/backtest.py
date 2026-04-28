"""
투찰가 예측 백테스트 스크립트.

학습셋: 2023-01-01 ~ 2024-12-31
검증셋: 2025-01-01 이후 (기본값, --since 로 변경 가능)

사용법:
  python scripts/backtest.py
  python scripts/backtest.py --since 2025-01-01
"""

import argparse
import asyncio
import csv
import io
import os
import sys
from collections import Counter

# Windows 터미널 UTF-8 출력 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, select

from app.db.models import BidsHistory, BidLicenseType, ProjectBucket
from app.db.session import AsyncSessionLocal
from app.data.fallback import get_rates_with_fallback
from app.engine.statistics import trimmed_median, mad
from app.engine.calculator import calculate_single


CUTOFF_DATE = date(2025, 1, 1)


async def run_backtest(since: date) -> list[dict]:
    results = []

    async with AsyncSessionLocal() as db:
        # 각 공고의 "대표 공종": 비상호허용(is_mutual=False) 중 첫 번째, 없으면 전체 중 첫 번째
        primary_type_sq = (
            select(BidLicenseType.type_name)
            .where(BidLicenseType.project_id == BidsHistory.project_id)
            .where(BidLicenseType.is_mutual == False)
            .order_by(BidLicenseType.id)
            .limit(1)
            .correlate(BidsHistory)
            .scalar_subquery()
        )
        fallback_type_sq = (
            select(BidLicenseType.type_name)
            .where(BidLicenseType.project_id == BidsHistory.project_id)
            .order_by(BidLicenseType.id)
            .limit(1)
            .correlate(BidsHistory)
            .scalar_subquery()
        )

        rows = (await db.execute(
            select(
                BidsHistory,
                func.coalesce(primary_type_sq, fallback_type_sq).label("primary_type"),
            ).where(
                BidsHistory.bid_date >= since,
                BidsHistory.bid_type == "적격심사",
                BidsHistory.bid_date.isnot(None),
            ).order_by(BidsHistory.bid_date)
        )).all()

        print(f"검증셋: {len(rows)}건 (since={since})")

        for i, row in enumerate(rows, 1):
            if i % 500 == 0:
                print(f"  처리 중... {i}/{len(rows)}")

            bid = row.BidsHistory
            primary_type = row.primary_type
            if not primary_type:
                continue

            bucket_id = ProjectBucket.get_bucket_id(bid.base_price)

            rates, fallback_level = await get_rates_with_fallback(
                db=db,
                client_name=bid.client_name or "",
                region=bid.region or "",
                project_type=primary_type,
                bucket_id=bucket_id,
                client_id=bid.client_id,
                before_date=since,
            )

            if not rates:
                continue

            predicted_rate = trimmed_median(rates)
            mad_val = mad(rates)

            calc = calculate_single(
                base_price=bid.base_price,
                lower_limit_rate=bid.lower_limit_rate,
                predicted_rate=predicted_rate,
                offset=Decimal("0"),
            )
            bid_price = calc["price_krw"]

            actual_rate = float(bid.adjustment_rate)
            est_price = int(bid.base_price * actual_rate)
            lower_bound = int(est_price * float(bid.lower_limit_rate))
            in_range = lower_bound <= bid_price <= est_price

            rate_error = abs(float(predicted_rate) - actual_rate)

            results.append({
                "project_id":     bid.project_id,
                "client_name":    bid.client_name or "",
                "project_type":   primary_type,
                "base_price":     bid.base_price,
                "actual_rate":    round(actual_rate, 6),
                "predicted_rate": round(float(predicted_rate), 6),
                "rate_error":     round(rate_error, 6),
                "mad_value":      round(float(mad_val), 6),
                "bid_price":      bid_price,
                "est_price":      est_price,
                "lower_bound":    lower_bound,
                "in_range":       in_range,
                "fallback_level": fallback_level,
                "bid_date":       str(bid.bid_date),
            })

    return results


def save_csv(results: list[dict], path: Path) -> None:
    if not results:
        print("결과 없음 — CSV 저장 스킵")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"CSV 저장: {path} ({len(results)}건)")


def _section_stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    errors = [r["rate_error"] for r in rows]
    in_range_cnt = sum(1 for r in rows if r["in_range"])
    total = len(rows)
    fallback_dist = Counter(r["fallback_level"] for r in rows)
    top5 = sorted(rows, key=lambda r: r["rate_error"], reverse=True)[:5]
    return {
        "total": total,
        "avg_error": round(sum(errors) / total, 6),
        "median_error": round(sorted(errors)[total // 2], 6),
        "in_range_rate": round(in_range_cnt / total * 100, 1),
        "fallback_dist": dict(fallback_dist),
        "top5": top5,
    }


def save_md(results: list[dict], path: Path, since: date) -> None:
    if not results:
        print("결과 없음 — MD 저장 스킵")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)
    errors = [r["rate_error"] for r in results]
    in_range_cnt = sum(1 for r in results if r["in_range"])
    avg_err = round(sum(errors) / total, 6)
    in_range_pct = round(in_range_cnt / total * 100, 1)

    types = sorted(set(r["project_type"] for r in results))
    sections = {t: _section_stats([r for r in results if r["project_type"] == t]) for t in types}

    type_counts = " / ".join(
        f"{t} {len([r for r in results if r['project_type'] == t]):,}건" for t in types
    )

    lines = [
        f"# 백테스트 리포트 — {today}",
        "",
        f"> 학습셋: 2023-01-01 ~ {since} 직전 / 검증셋: {since} 이후",
        "",
        "## 전체 요약",
        "",
        "| 지표 | 값 |",
        "|------|----|",
        f"| 검증 건수 | {total:,}건 ({type_counts}) |",
        f"| 평균 사정률 오차 | {avg_err:.6f} |",
        f"| 낙찰 구간 진입율 | {in_range_pct}% |",
        "",
    ]

    for ptype, stats in sections.items():
        if not stats:
            continue
        fb_str = " / ".join(f"{k} {v}건" for k, v in sorted(stats["fallback_dist"].items()))
        lines += [
            f"## {ptype}",
            "",
            "| 지표 | 값 |",
            "|------|----|",
            f"| 검증 건수 | {stats['total']:,}건 |",
            f"| 평균 사정률 오차 | {stats['avg_error']:.6f} |",
            f"| 중간값 오차 | {stats['median_error']:.6f} |",
            f"| 낙찰 구간 진입율 | {stats['in_range_rate']}% |",
            f"| fallback 분포 | {fb_str} |",
            "",
            "### 오차 큰 케이스 TOP5",
            "",
            "| 공고번호 | 발주처 | 예측 | 실제 | 오차 | 진입 |",
            "|---------|-------|------|------|------|------|",
        ]
        for r in stats["top5"]:
            lines.append(
                f"| {r['project_id']} | {r['client_name'][:15]} | "
                f"{r['predicted_rate']:.4f} | {r['actual_rate']:.4f} | "
                f"{r['rate_error']:.4f} | {'✓' if r['in_range'] else '✗'} |"
            )
        lines.append("")

    lines += ["## 결론", ""]
    weak = [(t, s) for t, s in sections.items() if s and s["in_range_rate"] < 50]
    strong = [(t, s) for t, s in sections.items() if s and s["in_range_rate"] >= 70]
    if strong:
        lines.append("- 잘 맞는 공종: " + ", ".join(f"{t}({s['in_range_rate']}%)" for t, s in strong))
    if weak:
        lines.append("- 취약한 공종: " + ", ".join(f"{t}({s['in_range_rate']}%)" for t, s in weak))
    if not weak and not strong:
        lines.append("- 전체적으로 보통 수준의 예측 성능")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"MD 저장: {path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="투찰가 예측 백테스트")
    parser.add_argument(
        "--since",
        default=str(CUTOFF_DATE),
        help=f"검증 시작일 (기본값: {CUTOFF_DATE})",
    )
    args = parser.parse_args()
    since = date.fromisoformat(args.since)

    print(f"백테스트 시작 — 검증셋: {since} 이후")
    results = await run_backtest(since)

    if not results:
        print("예측 가능한 레코드가 없습니다.")
        return

    today_str = datetime.now().strftime("%Y%m%d")
    csv_path = Path(f"data/backtest_{today_str}.csv")
    md_path  = Path(f"data/backtest_{today_str}.md")

    save_csv(results, csv_path)
    save_md(results, md_path, since)

    total = len(results)
    avg_err = sum(r["rate_error"] for r in results) / total
    in_range_pct = sum(1 for r in results if r["in_range"]) / total * 100
    print(f"\n{'='*50}")
    print(f"검증 건수    : {total:,}건")
    print(f"평균 오차    : {avg_err:.6f}")
    print(f"구간 진입율  : {in_range_pct:.1f}%")
    print(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(main())
