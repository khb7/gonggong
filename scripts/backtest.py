"""
투찰가 예측 백테스트 스크립트.

학습셋: 2023-01-01 ~ 2024-12-31
검증셋: 2025-01-01 이후 (기본값, --since 로 변경 가능)

사용법:
  python scripts/backtest.py
  python scripts/backtest.py --since 2025-01-01

측정 지표:
  - MAE       : 평균 절대 오차 (|predicted - actual|)
  - MAPE      : 평균 절대 백분율 오차 (|error| / actual × 100)
  - Bias      : 평균 편향 (predicted - actual, 양수=과대예측, 음수=과소예측)
  - P90 오차  : 오차 90번째 백분위 (최악 케이스 범위)
  - 구간진입율 : 중립 투찰가(offset=0)가 낙찰 구간에 들어간 비율
  - 전략적중율 : 실제 전략(offset=-MAD, aggressive)으로 낙찰 구간 진입 비율
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

from scipy.stats import ks_2samp
from sqlalchemy import func, select

from app.db.models import BidsHistory, BidLicenseType, BidParticipants, ProjectBucket
from app.db.session import AsyncSessionLocal
from app.data.fallback import get_rates_with_fallback
from app.engine.statistics import trimmed_median, mad
from app.engine.calculator import calculate_single


CUTOFF_DATE = date(2025, 1, 1)

BUCKET_LABELS = {
    1: "~1억",
    2: "1억~5억",
    3: "5억~20억",
    4: "20억+",
}


async def run_backtest(since: date, until: date | None = None) -> list[dict]:
    """
    since ~ until(미포함) 기간의 데이터를 검증셋으로 사용.
    fallback의 before_date는 항상 since로 고정 (데이터 누출 방지).
    until=None 이면 since 이후 전체.
    """
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

        filters = [
            BidsHistory.bid_date >= since,
            BidsHistory.bid_type == "적격심사",
            BidsHistory.bid_date.isnot(None),
        ]
        if until:
            filters.append(BidsHistory.bid_date < until)

        rows = (await db.execute(
            select(
                BidsHistory,
                func.coalesce(primary_type_sq, fallback_type_sq).label("primary_type"),
            ).where(*filters).order_by(BidsHistory.bid_date)
        )).all()

        label = f"{since} ~ {until}" if until else f"{since} 이후"
        print(f"검증셋: {len(rows)}건 ({label})")

        # 검증셋 프로젝트의 실제 낙찰자 bid_amount 벌크 조회
        project_ids = [r.BidsHistory.project_id for r in rows]
        winner_rows = (await db.execute(
            select(BidParticipants.project_id, BidParticipants.bid_amount)
            .where(BidParticipants.project_id.in_(project_ids))
            .where(BidParticipants.is_winner == True)
        )).all()
        winner_bid_map: dict[str, int] = {r.project_id: r.bid_amount for r in winner_rows}

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

            # 중립 투찰가 (offset=0): 예측 정확도 기준선
            calc_neutral = calculate_single(
                base_price=bid.base_price,
                lower_limit_rate=bid.lower_limit_rate,
                predicted_rate=predicted_rate,
                offset=Decimal("0"),
            )

            # 실제 전략 투찰가 (offset=+MAD, aggressive): 실전 시뮬레이션
            calc_agg = calculate_single(
                base_price=bid.base_price,
                lower_limit_rate=bid.lower_limit_rate,
                predicted_rate=predicted_rate,
                offset=mad_val,
            )

            actual_rate = float(bid.adjustment_rate)
            est_price = int(bid.base_price * actual_rate)
            lower_bound = int(est_price * float(bid.lower_limit_rate))

            neutral_price = calc_neutral["price_krw"]
            agg_price = calc_agg["price_krw"]

            in_range_neutral = lower_bound <= neutral_price <= est_price
            in_range_agg     = lower_bound <= agg_price <= est_price
            # 실패 원인 분해 (전략 기준)
            too_low_agg  = agg_price < lower_bound   # 하한선 이탈
            too_high_agg = agg_price > est_price      # 예정가격 초과

            # 실제 낙찰자 대비 시뮬레이션 낙찰 여부
            winner_bid_amt = winner_bid_map.get(bid.project_id)
            simulated_win = bool(
                winner_bid_amt and lower_bound <= agg_price <= winner_bid_amt
            )

            # 오차 지표
            pred_f = float(predicted_rate)
            rate_error = abs(pred_f - actual_rate)          # MAE용
            bias = pred_f - actual_rate                      # 양수=과대, 음수=과소
            mape = rate_error / actual_rate * 100 if actual_rate else 0.0

            results.append({
                "project_id":       bid.project_id,
                "client_name":      bid.client_name or "",
                "region":           bid.region or "",
                "project_type":     primary_type,
                "bucket_id":        bucket_id,
                "base_price":       bid.base_price,
                "actual_rate":      round(actual_rate, 6),
                "predicted_rate":   round(pred_f, 6),
                "rate_error":       round(rate_error, 6),
                "bias":             round(bias, 6),
                "mape":             round(mape, 4),
                "mad_value":        round(float(mad_val), 6),
                "n_samples":        len(rates),
                # 중립 투찰 (offset=0)
                "neutral_price":    neutral_price,
                "in_range_neutral": in_range_neutral,
                # 실전 전략 (offset=+MAD)
                "agg_price":        agg_price,
                "in_range_agg":     in_range_agg,
                "too_low_agg":      too_low_agg,
                "too_high_agg":     too_high_agg,
                "simulated_win":    simulated_win,
                "has_participant_data": winner_bid_amt is not None,
                "lower_limit_rate":  float(bid.lower_limit_rate),
                "est_price":        est_price,
                "lower_bound":      lower_bound,
                "fallback_level":   fallback_level,
                "bid_date":         str(bid.bid_date),
            })

    return results


def monthly_windows(start: date, end: date) -> list[tuple[date, date]]:
    """[start, end) 기간을 월별 (window_start, window_end) 튜플 리스트로 반환."""
    windows = []
    cur = date(start.year, start.month, 1)
    while cur < end:
        if cur.month == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, cur.month + 1, 1)
        windows.append((cur, min(nxt, end)))
        cur = nxt
    return windows


def _wf_key_metrics(results: list[dict]) -> dict:
    """Walk-Forward 한 윈도우의 핵심 지표만 추출."""
    if not results:
        return {}
    total = len(results)
    errors = [r["rate_error"] for r in results]
    biases = [r["bias"] for r in results]
    return {
        "n":            total,
        "mae":          round(sum(errors) / total, 6),
        "bias":         round(sum(biases) / total, 6),
        "hit_rate":     round(sum(1 for r in results if r["in_range_agg"]) / total * 100, 1),
        "too_low_pct":  round(sum(1 for r in results if r["too_low_agg"]) / total * 100, 1),
        "too_high_pct": round(sum(1 for r in results if r["too_high_agg"]) / total * 100, 1),
        "fallback_top": max(
            Counter(r["fallback_level"] for r in results),
            key=Counter(r["fallback_level"] for r in results).get,
        ),
    }


async def run_walk_forward(wf_start: date, since: date) -> list[dict]:
    """
    wf_start ~ since 기간을 월별로 나눠 각 윈도우를 검증.

    각 윈도우:
      - 학습셋: 윈도우 시작일 이전 전체
      - 검증셋: 해당 월 1일 ~ 말일
    """
    windows = monthly_windows(wf_start, since)
    timeline = []

    for i, (ws, we) in enumerate(windows, 1):
        month_label = ws.strftime("%Y-%m")
        print(f"  Walk-Forward [{i}/{len(windows)}] {month_label} ... ", end="", flush=True)

        results = await run_backtest(since=ws, until=we)
        metrics = _wf_key_metrics(results)
        if not metrics:
            print("데이터 없음")
            continue

        timeline.append({"month": month_label, **metrics})
        print(f"{metrics['n']}건  MAE={metrics['mae']:.5f}  hit={metrics['hit_rate']}%")

    return timeline


def save_wf_csv(timeline: list[dict], path: Path) -> None:
    if not timeline:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=timeline[0].keys())
        writer.writeheader()
        writer.writerows(timeline)
    print(f"WF CSV 저장: {path} ({len(timeline)}개월)")


def save_wf_md(timeline: list[dict], path: Path, wf_start: date, since: date) -> None:
    if not timeline:
        print("Walk-Forward 결과 없음 — MD 저장 스킵")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    n_windows = len(timeline)

    def _avg(key: str) -> float:
        return sum(r[key] for r in timeline) / n_windows

    def _std(key: str) -> float:
        avg = _avg(key)
        return (sum((r[key] - avg) ** 2 for r in timeline) / n_windows) ** 0.5

    # 추세: 전반부 vs 후반부 평균 비교
    half = n_windows // 2
    first_half  = timeline[:half] if half else timeline
    second_half = timeline[half:] if half else timeline

    def _half_avg(subset: list[dict], key: str) -> float:
        return sum(r[key] for r in subset) / len(subset) if subset else 0.0

    hit_trend = _half_avg(second_half, "hit_rate") - _half_avg(first_half, "hit_rate")
    mae_trend  = _half_avg(second_half, "mae")  - _half_avg(first_half, "mae")

    lines = [
        f"# Walk-Forward 검증 리포트 — {today}",
        "",
        f"> 검증 기간: {wf_start} ~ {since} ({n_windows}개월)",
        "> 매월 해당 월 이전 전체 데이터를 학습셋으로 사용",
        "",
        "## 요약 통계",
        "",
        "| 지표 | 평균 | 표준편차 | 최소 | 최대 |",
        "|------|------|---------|------|------|",
        f"| 건수 | {_avg('n'):.0f} | {_std('n'):.1f} | {min(r['n'] for r in timeline)} | {max(r['n'] for r in timeline)} |",
        f"| MAE | {_avg('mae'):.6f} | {_std('mae'):.6f} | {min(r['mae'] for r in timeline):.6f} | {max(r['mae'] for r in timeline):.6f} |",
        f"| Bias | {_avg('bias'):+.6f} | {_std('bias'):.6f} | {min(r['bias'] for r in timeline):+.6f} | {max(r['bias'] for r in timeline):+.6f} |",
        f"| Hit Rate | {_avg('hit_rate'):.1f}% | {_std('hit_rate'):.1f}%p | {min(r['hit_rate'] for r in timeline):.1f}% | {max(r['hit_rate'] for r in timeline):.1f}% |",
        f"| Too Low | {_avg('too_low_pct'):.1f}% | {_std('too_low_pct'):.1f}%p | — | — |",
        f"| Too High | {_avg('too_high_pct'):.1f}% | {_std('too_high_pct'):.1f}%p | — | — |",
        "",
        "## 월별 성능 추이",
        "",
        "| 월 | 건수 | MAE | Bias | Hit Rate | Too Low | Too High | Fallback |",
        "|---|------|-----|------|---------|---------|---------|---------|",
    ]

    for r in timeline:
        bias_sign = "+" if r["bias"] >= 0 else ""
        lines.append(
            f"| {r['month']} | {r['n']} | {r['mae']:.6f} | "
            f"{bias_sign}{r['bias']:.6f} | **{r['hit_rate']}%** | "
            f"{r['too_low_pct']}% | {r['too_high_pct']}% | {r['fallback_top']} |"
        )

    lines += [
        "",
        "## 추세 분석",
        "",
    ]

    # Hit Rate 추세
    if abs(hit_trend) < 2:
        lines.append(f"- **Hit Rate**: 안정적 (전반부↔후반부 {hit_trend:+.1f}%p)")
    elif hit_trend > 0:
        lines.append(f"- **Hit Rate**: 개선 추세 (전반부↔후반부 {hit_trend:+.1f}%p) — 데이터 누적 효과")
    else:
        lines.append(f"- **Hit Rate**: 하락 추세 (전반부↔후반부 {hit_trend:+.1f}%p) — 분포 이동 가능성, KS test 확인")

    # MAE 추세
    if abs(mae_trend) < 0.001:
        lines.append(f"- **MAE**: 안정적 (전반부↔후반부 {mae_trend:+.6f})")
    elif mae_trend > 0:
        lines.append(f"- **MAE**: 오차 증가 추세 ({mae_trend:+.6f}) — 분포 이동 또는 시장 변화")
    else:
        lines.append(f"- **MAE**: 오차 감소 추세 ({mae_trend:+.6f}) — 예측 정확도 개선 중")

    # 변동성 진단
    hit_std = _std("hit_rate")
    if hit_std > 10:
        lines.append(f"- **불안정**: Hit Rate 표준편차 {hit_std:.1f}%p — 월별 편차가 크므로 단일 백테스트 수치를 신뢰하기 어려움")
    elif hit_std < 5:
        lines.append(f"- **안정적**: Hit Rate 표준편차 {hit_std:.1f}%p — 일관된 성능")

    # 최악 월 / 최선 월
    worst = min(timeline, key=lambda r: r["hit_rate"])
    best  = max(timeline, key=lambda r: r["hit_rate"])
    lines += [
        "",
        f"- **최선 월**: {best['month']} (hit_rate {best['hit_rate']}%, MAE {best['mae']:.6f})",
        f"- **최악 월**: {worst['month']} (hit_rate {worst['hit_rate']}%, MAE {worst['mae']:.6f})",
        "",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"WF MD 저장: {path}")


async def fetch_train_rates(since: date) -> dict[str, list[float]]:
    """
    학습셋 (since 이전) 실제 사정률을 공종별로 조회.
    KS test의 기준 분포로 사용한다.
    """
    async with AsyncSessionLocal() as db:
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
                BidsHistory.adjustment_rate,
                func.coalesce(primary_type_sq, fallback_type_sq).label("primary_type"),
            ).where(
                BidsHistory.bid_date < since,
                BidsHistory.bid_type == "적격심사",
                BidsHistory.adjustment_rate.isnot(None),
            )
        )).all()

    by_type: dict[str, list[float]] = {}
    for row in rows:
        ptype = row.primary_type
        if not ptype:
            continue
        by_type.setdefault(ptype, []).append(float(row.adjustment_rate))
    return by_type


def _run_ks(train: list[float], val: list[float]) -> dict:
    """두 샘플 간 KS 검정 실행."""
    stat, pval = ks_2samp(train, val)
    if stat < 0.05:
        severity = "없음"
    elif stat < 0.10:
        severity = "경미"
    elif stat < 0.20:
        severity = "주의"
    else:
        severity = "심각"
    return {
        "n_train":  len(train),
        "n_val":    len(val),
        "D":        round(stat, 4),
        "p_value":  round(pval, 4),
        "drifted":  pval < 0.05,
        "severity": severity,
    }


def run_ks_analysis(
    since: date,
    train_by_type: dict[str, list[float]],
    results: list[dict],
) -> dict:
    """
    공종별 + 전체 KS test 실행.

    Returns:
        {"overall": {...}, "by_type": {"실내건축": {...}, ...}}
    """
    val_all = [r["actual_rate"] for r in results]
    train_all = [v for vals in train_by_type.values() for v in vals]

    ks_results: dict = {}

    if len(train_all) >= 5 and len(val_all) >= 5:
        ks_results["overall"] = _run_ks(train_all, val_all)
    else:
        ks_results["overall"] = None

    by_type = {}
    types = sorted(set(r["project_type"] for r in results))
    for ptype in types:
        train_t = train_by_type.get(ptype, [])
        val_t   = [r["actual_rate"] for r in results if r["project_type"] == ptype]
        if len(train_t) >= 5 and len(val_t) >= 5:
            by_type[ptype] = _run_ks(train_t, val_t)
        else:
            by_type[ptype] = None
    ks_results["by_type"] = by_type

    return ks_results


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


def _percentile(sorted_vals: list[float], p: float) -> float:
    """p번째 백분위 값 반환 (0~100)."""
    if not sorted_vals:
        return 0.0
    idx = int(len(sorted_vals) * p / 100)
    idx = min(idx, len(sorted_vals) - 1)
    return sorted_vals[idx]


def _skewness(vals: list[float]) -> float:
    """Pearson 3차 모멘트 기반 왜도."""
    n = len(vals)
    if n < 3:
        return 0.0
    mean = sum(vals) / n
    variance = sum((x - mean) ** 2 for x in vals) / n
    std = variance ** 0.5
    if std == 0:
        return 0.0
    return sum((x - mean) ** 3 for x in vals) / (n * std ** 3)


def _section_stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    total = len(rows)
    errors  = [r["rate_error"] for r in rows]
    biases  = [r["bias"] for r in rows]
    mapes   = [r["mape"] for r in rows]
    actuals = [r["actual_rate"] for r in rows]
    samples = [r["n_samples"] for r in rows]
    sorted_errors  = sorted(errors)
    sorted_actuals = sorted(actuals)
    sorted_samples = sorted(samples)

    in_range_neutral = sum(1 for r in rows if r["in_range_neutral"])
    in_range_agg     = sum(1 for r in rows if r["in_range_agg"])
    too_low_cnt      = sum(1 for r in rows if r["too_low_agg"])
    too_high_cnt     = sum(1 for r in rows if r["too_high_agg"])
    fallback_dist    = Counter(r["fallback_level"] for r in rows)
    top5 = sorted(rows, key=lambda r: r["rate_error"], reverse=True)[:5]

    # 참여자 데이터 기반 시뮬레이션 낙찰율
    rows_with_data = [r for r in rows if r.get("has_participant_data")]
    simulated_win_cnt  = sum(1 for r in rows_with_data if r["simulated_win"])
    simulated_win_rate = round(simulated_win_cnt / len(rows_with_data) * 100, 1) if rows_with_data else None
    participant_coverage = round(len(rows_with_data) / total * 100, 1)

    # actual_rate 기술 통계
    actual_mean = sum(actuals) / total
    actual_std  = (sum((x - actual_mean) ** 2 for x in actuals) / total) ** 0.5

    # R² (결정계수)
    predicted = [r["predicted_rate"] for r in rows]
    ss_tot = sum((a - actual_mean) ** 2 for a in actuals)
    ss_res = sum((a - p) ** 2 for a, p in zip(actuals, predicted))
    r_squared = round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else 0.0

    # Skill Score (vs 항상 actual_mean 예측하는 기준선)
    mae_val      = sum(errors) / total
    baseline_mae = sum(abs(a - actual_mean) for a in actuals) / total
    skill_score  = round(1 - mae_val / baseline_mae, 4) if baseline_mae > 0 else 0.0

    # Multi-level MAD Coverage
    def _mad_cov(k: float) -> float:
        return round(
            sum(1 for r in rows if r["rate_error"] <= k * r["mad_value"]) / total * 100, 1
        )
    mad_coverage_half = _mad_cov(0.5)
    mad_coverage      = _mad_cov(1.0)   # 기존 지표, 이름 유지
    mad_coverage_2x   = _mad_cov(2.0)
    mad_coverage_3x   = _mad_cov(3.0)

    # 샘플 수 vs 오차 상관관계 (Pearson)
    def _pearson(xs: list, ys: list) -> float:
        n = len(xs)
        if n < 3:
            return 0.0
        mx, my = sum(xs) / n, sum(ys) / n
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        sx  = sum((x - mx) ** 2 for x in xs) ** 0.5
        sy  = sum((y - my) ** 2 for y in ys) ** 0.5
        return round(cov / (sx * sy), 4) if sx * sy > 0 else 0.0

    sample_error_corr = _pearson(samples, errors)

    # 샘플 충분성
    clt_pct       = round(sum(1 for s in samples if s >= 30) / total * 100, 1)
    high_conf_pct = round(sum(1 for s in samples if s >= 50) / total * 100, 1)

    return {
        "total":            total,
        # 오차 지표
        "mae":              round(mae_val, 6),
        "mape":             round(sum(mapes) / total, 4),
        "bias":             round(sum(biases) / total, 6),
        "median_error":     round(sorted_errors[total // 2], 6),
        "p25_error":        round(_percentile(sorted_errors, 25), 6),
        "p75_error":        round(_percentile(sorted_errors, 75), 6),
        "p90_error":        round(_percentile(sorted_errors, 90), 6),
        "p95_error":        round(_percentile(sorted_errors, 95), 6),
        "skewness":         round(_skewness(errors), 4),
        # 모델 성능
        "r_squared":        r_squared,
        "skill_score":      skill_score,
        "mad_coverage":         mad_coverage,
        "mad_coverage_half":    mad_coverage_half,
        "mad_coverage_2x":      mad_coverage_2x,
        "mad_coverage_3x":      mad_coverage_3x,
        "sample_error_corr":    sample_error_corr,
        # 구간 진입
        "in_range_neutral": round(in_range_neutral / total * 100, 1),
        "in_range_agg":     round(in_range_agg / total * 100, 1),
        "too_low_pct":      round(too_low_cnt / total * 100, 1),
        "too_high_pct":     round(too_high_cnt / total * 100, 1),
        # 시뮬레이션 낙찰율 (참여자 데이터 보유 건 기준)
        "simulated_win_rate":    simulated_win_rate,
        "participant_coverage":  participant_coverage,
        # 데이터 특성
        "actual_mean":      round(actual_mean, 6),
        "actual_std":       round(actual_std, 6),
        "actual_min":       round(sorted_actuals[0], 6),
        "actual_max":       round(sorted_actuals[-1], 6),
        "actual_median":    round(sorted_actuals[total // 2], 6),
        "n_samples_median": int(sorted_samples[total // 2]),
        "n_samples_min":    int(sorted_samples[0]),
        "n_samples_max":    int(sorted_samples[-1]),
        "clt_pct":          clt_pct,
        "high_conf_pct":    high_conf_pct,
        "fallback_dist":    dict(fallback_dist),
        "top5":             top5,
    }


SWEEP_MULTIPLIERS = [-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0]


def run_offset_sweep(results: list[dict]) -> list[dict]:
    """
    MAD 배수별 hit rate를 계산해 최적 offset을 탐색한다.

    각 배수 m에 대해:
        bid_price = base_price × predicted_rate × (lower_limit_rate + m × MAD)
        hit = lower_bound <= bid_price <= est_price
    """
    sweep = []
    for mult in SWEEP_MULTIPLIERS:
        hit = too_low = too_high = 0
        for r in results:
            offset = mult * r["mad_value"]
            llr    = r["lower_limit_rate"]
            bid    = int(r["base_price"] * r["predicted_rate"] * (llr + offset))
            lb, ep = r["lower_bound"], r["est_price"]
            if bid < lb:
                too_low += 1
            elif bid > ep:
                too_high += 1
            else:
                hit += 1
        total = len(results)
        label = f"{mult:+.1f}×MAD" if mult != 0 else "0 (중립)"
        sweep.append({
            "label":       label,
            "multiplier":  mult,
            "hit_rate":    round(hit / total * 100, 1),
            "too_low_pct": round(too_low / total * 100, 1),
            "too_high_pct":round(too_high / total * 100, 1),
        })
    return sweep


def _bucket_stats(results: list[dict]) -> dict:
    """버킷(금액 구간)별 성능 분석."""
    buckets = sorted(set(r["bucket_id"] for r in results))
    out = {}
    for b in buckets:
        rows = [r for r in results if r["bucket_id"] == b]
        out[b] = _section_stats(rows)
    return out


def _fallback_level_stats(results: list[dict]) -> dict:
    """Fallback 레벨별 예측 정확도 비교."""
    levels = sorted(set(r["fallback_level"] for r in results))
    out = {}
    for lv in levels:
        rows = [r for r in results if r["fallback_level"] == lv]
        out[lv] = _section_stats(rows)
    return out


# n_samples 구간 정의: (레이블, 하한 포함, 상한 미포함)
SAMPLE_BUCKETS = [
    ("20~29건 (MIN 기준)",  20,  30),
    ("30~49건 (CLT 기준)",  30,  50),
    ("50~99건 (고신뢰)",    50, 100),
    ("100건+  (최고신뢰)", 100, 10_000),
]


def _sample_bucket_stats(results: list[dict]) -> list[dict]:
    """
    n_samples 구간별 MAE / hit_rate 비교.
    MIN_SAMPLE_SIZE(현재 20) 기준이 적절한지 검증하는 데 사용.
    """
    out = []
    for label, lo, hi in SAMPLE_BUCKETS:
        rows = [r for r in results if lo <= r["n_samples"] < hi]
        if not rows:
            continue
        total = len(rows)
        mae = sum(r["rate_error"] for r in rows) / total
        hit = sum(1 for r in rows if r["in_range_agg"]) / total * 100
        tl  = sum(1 for r in rows if r["too_low_agg"]) / total * 100
        th  = sum(1 for r in rows if r["too_high_agg"]) / total * 100
        out.append({
            "label":       label,
            "n":           total,
            "mae":         round(mae, 6),
            "hit_rate":    round(hit, 1),
            "too_low_pct": round(tl, 1),
            "too_high_pct":round(th, 1),
        })
    return out


def _stats_tables(stats: dict) -> list[str]:
    """공통 지표 테이블 3개 생성: 오차 / 구간 진입 / 데이터 특성."""
    bias_label  = "과대예측" if stats["bias"] > 0 else "과소예측"
    skew_label  = "우편향(드물게 크게 틀림)" if stats["skewness"] > 1 else (
                  "좌편향" if stats["skewness"] < -1 else "대칭에 가까움")
    fb_str = " / ".join(f"{k} {v}건" for k, v in sorted(stats["fallback_dist"].items()))

    lines = [
        "**오차 지표**",
        "",
        "| 지표 | 값 |",
        "|------|----|",
        f"| 검증 건수 | {stats['total']:,}건 |",
        f"| MAE (평균 절대 오차) | {stats['mae']:.6f} |",
        f"| MAPE (평균 절대 % 오차) | {stats['mape']:.4f}% |",
        f"| Bias (편향) | {stats['bias']:+.6f} ({bias_label}) |",
        f"| P25 오차 | {stats['p25_error']:.6f} |",
        f"| P50 오차 (중간값) | {stats['median_error']:.6f} |",
        f"| P75 오차 | {stats['p75_error']:.6f} |",
        f"| P90 오차 | {stats['p90_error']:.6f} |",
        f"| P95 오차 | {stats['p95_error']:.6f} |",
        f"| Skewness (왜도) | {stats['skewness']:+.4f} ({skew_label}) |",
        "",
        "**모델 성능**",
        "",
        "| 지표 | 값 | 해석 |",
        "|------|----|------|",
        f"| R² (결정계수) | {stats['r_squared']:.4f} | "
        f"{'모델이 분산을 잘 설명함' if stats['r_squared'] > 0.5 else ('기준선 수준' if stats['r_squared'] > 0 else '기준선보다 나쁨')} |",
        f"| Skill Score | {stats['skill_score']:+.4f} | "
        f"{'평균 예측 대비 {:.1f}% 향상'.format(stats['skill_score']*100) if stats['skill_score'] > 0 else '평균 예측과 동일하거나 나쁨'} |",
        f"| MAD Coverage | {stats['mad_coverage']}% | "
        f"{'과대 추정(보수적)' if stats['mad_coverage'] > 60 else ('과소 추정(위험)' if stats['mad_coverage'] < 40 else '양호(~50% 기대)')} |",
        "",
        "**신뢰 구간 & 불확실성**",
        "",
        "| 범위 | coverage | 기대값 |",
        "|------|---------|--------|",
        f"| ±0.5×MAD | {stats['mad_coverage_half']}% | ~25% |",
        f"| ±1×MAD   | {stats['mad_coverage']}% | ~50% |",
        f"| ±2×MAD   | {stats['mad_coverage_2x']}% | ~75% |",
        f"| ±3×MAD   | {stats['mad_coverage_3x']}% | ~90% |",
        "",
        f"샘플 수 vs 오차 상관: **{stats['sample_error_corr']:+.4f}** "
        f"({'음수=샘플 많을수록 정확' if stats['sample_error_corr'] < 0 else '양수=샘플 수 효과 없음 또는 역효과'})",
        "",
        "**구간 진입 분석**",
        "",
        "| 지표 | 값 |",
        "|------|----|",
        f"| 중립 진입율 (offset=0) | {stats['in_range_neutral']}% |",
        f"| 전략 진입율 (offset=+MAD) | {stats['in_range_agg']}% |",
        f"| 하한선 이탈 (too low) | {stats['too_low_pct']}% |",
        f"| 예정가 초과 (too high) | {stats['too_high_pct']}% |",
        f"| **시뮬레이션 낙찰율** | **{stats['simulated_win_rate']}%** (참여자 데이터 {stats['participant_coverage']}% 커버) |"
        if stats['simulated_win_rate'] is not None else "",
        "",
        "**데이터 특성**",
        "",
        "| 지표 | 값 |",
        "|------|----|",
        f"| 실제 사정률 평균 | {stats['actual_mean']:.6f} |",
        f"| 실제 사정률 중간값 | {stats['actual_median']:.6f} |",
        f"| 실제 사정률 표준편차 | {stats['actual_std']:.6f} |",
        f"| 실제 사정률 범위 | {stats['actual_min']:.4f} ~ {stats['actual_max']:.4f} |",
        f"| 샘플 수 중간값 | {stats['n_samples_median']}건 |",
        f"| 샘플 수 범위 | {stats['n_samples_min']} ~ {stats['n_samples_max']}건 |",
        f"| CLT 충족율 (n≥30) | {stats['clt_pct']}% |",
        f"| 고신뢰 기준 (n≥50) | {stats['high_conf_pct']}% |",
        f"| fallback 분포 | {fb_str} |",
        "",
    ]
    return lines


def _sweep_md_section(sweep: list[dict]) -> list[str]:
    """Offset Sweep 결과 MD 섹션."""
    best = max(sweep, key=lambda x: x["hit_rate"])
    lines = [
        "## Offset Sweep (최적 offset 탐색)",
        "",
        "> MAD 배수를 바꿔가며 낙찰 구간 진입율을 측정한다.",
        "> 현재 전략은 **-1.0×MAD**. 다른 배수와 비교해 최적값을 확인한다.",
        "",
        "| offset | 진입율 | too_low | too_high |",
        "|--------|--------|---------|---------|",
    ]
    for row in sweep:
        marker = " ◀ 현재" if row["multiplier"] == 1.0 else (
                 " ★ 최적" if row["multiplier"] == best["multiplier"] and row["multiplier"] != -1.0 else "")
        lines.append(
            f"| {row['label']}{marker} | **{row['hit_rate']}%** | "
            f"{row['too_low_pct']}% | {row['too_high_pct']}% |"
        )
    lines += [
        "",
        f"- **최적 offset**: {best['label']} (진입율 {best['hit_rate']}%)",
    ]
    current = next(r for r in sweep if r["multiplier"] == 1.0)
    diff = best["hit_rate"] - current["hit_rate"]
    if diff > 2:
        lines.append(
            f"- **권고**: 현재(-1.0×MAD) 대비 {best['label']}로 변경 시 {diff:.1f}%p 향상 가능"
        )
    else:
        lines.append("- **현재 전략(-1.0×MAD)이 이미 최적 또는 근접**")
    lines.append("")
    return lines


def _ks_md_section(ks_results: dict) -> list[str]:
    """KS test 결과 MD 섹션 생성."""
    lines = ["## 분포 이동 검정 (KS Test)", ""]
    lines += [
        "> 학습셋(train)과 검증셋(val)의 실제 사정률 분포가 같은지 검정한다.",
        "> D값이 클수록 분포 차이가 크고, p < 0.05이면 이동이 통계적으로 유의하다.",
        "",
        "| 공종 | train n | val n | D 통계량 | p-value | 이동 여부 | 심각도 |",
        "|------|---------|-------|---------|---------|---------|------|",
    ]

    overall = ks_results.get("overall")
    if overall:
        drift_mark = "**⚠ 이동**" if overall["drifted"] else "안정"
        lines.append(
            f"| 전체 | {overall['n_train']:,} | {overall['n_val']:,} | "
            f"{overall['D']:.4f} | {overall['p_value']:.4f} | "
            f"{drift_mark} | {overall['severity']} |"
        )

    for ptype, ks in sorted(ks_results.get("by_type", {}).items()):
        if ks is None:
            lines.append(f"| {ptype} | — | — | — | — | 샘플 부족 | — |")
            continue
        drift_mark = "**⚠ 이동**" if ks["drifted"] else "안정"
        lines.append(
            f"| {ptype} | {ks['n_train']:,} | {ks['n_val']:,} | "
            f"{ks['D']:.4f} | {ks['p_value']:.4f} | "
            f"{drift_mark} | {ks['severity']} |"
        )

    lines += [
        "",
        "**심각도 기준**: D < 0.05 없음 / 0.05~0.10 경미 / 0.10~0.20 주의 / 0.20+ 심각",
        "",
    ]

    # 자동 해석
    drifted = [k for k, v in ks_results.get("by_type", {}).items() if v and v["drifted"]]
    if not drifted and (not overall or not overall["drifted"]):
        lines.append("- **결론**: 분포 이동 없음 — 학습셋이 검증셋을 잘 대표함")
    else:
        if overall and overall["drifted"]:
            lines.append(
                f"- **경고**: 전체 분포 이동 감지 (D={overall['D']:.4f}) — "
                "학습셋 재검토 또는 학습 기간 조정 고려"
            )
        if drifted:
            lines.append(
                "- **이동 감지 공종**: " + ", ".join(
                    f"{t}(D={ks_results['by_type'][t]['D']:.4f})" for t in drifted
                )
            )
        lines.append(
            "- **대응**: 이동이 심한 공종은 학습셋에서 최근 N개월 데이터만 사용하는 방식 고려"
        )
    lines.append("")
    return lines


def save_md(
    results: list[dict],
    path: Path,
    since: date,
    ks_results: dict | None = None,
    sweep: list[dict] | None = None,
) -> None:
    if not results:
        print("결과 없음 — MD 저장 스킵")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)
    overall = _section_stats(results)

    types = sorted(set(r["project_type"] for r in results))
    type_sections = {t: _section_stats([r for r in results if r["project_type"] == t]) for t in types}
    bucket_sections  = _bucket_stats(results)
    fb_sections      = _fallback_level_stats(results)
    sample_buckets   = _sample_bucket_stats(results)

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
        *_stats_tables(overall),
        f"> 검증 건수: {total:,}건 ({type_counts})",
        "",
    ]

    # ── 공종별 ──────────────────────────────────────────────────
    lines += ["## 공종별 분석", ""]
    for ptype, stats in type_sections.items():
        if not stats:
            continue
        lines += [f"### {ptype}", ""]
        lines += _stats_tables(stats)

        lines += [
            "#### 오차 큰 케이스 TOP5",
            "",
            "| 공고번호 | 발주처 | 예측 | 실제 | 오차 | 중립진입 | 전략진입 |",
            "|---------|-------|------|------|------|---------|---------|",
        ]
        for r in stats["top5"]:
            lines.append(
                f"| {r['project_id']} | {r['client_name'][:15]} | "
                f"{r['predicted_rate']:.4f} | {r['actual_rate']:.4f} | "
                f"{r['rate_error']:.4f} | "
                f"{'✓' if r['in_range_neutral'] else '✗'} | "
                f"{'✓' if r['in_range_agg'] else '✗'} |"
            )
        lines.append("")

    # ── 버킷(금액 구간)별 ─────────────────────────────────────
    lines += ["## 금액 구간별 분석", ""]
    lines += [
        "| 구간 | 건수 | MAE | MAPE | Bias | 전략진입율 | too_low | too_high |",
        "|------|------|-----|------|------|----------|---------|---------|",
    ]
    for b_id, stats in sorted(bucket_sections.items()):
        label = BUCKET_LABELS.get(b_id, str(b_id))
        bias_sign = "+" if stats["bias"] >= 0 else ""
        lines.append(
            f"| {label} | {stats['total']:,} | {stats['mae']:.6f} | "
            f"{stats['mape']:.4f}% | {bias_sign}{stats['bias']:.6f} | "
            f"{stats['in_range_agg']}% | {stats['too_low_pct']}% | {stats['too_high_pct']}% |"
        )
    lines.append("")

    # ── Fallback 레벨별 ───────────────────────────────────────
    lines += ["## Fallback 레벨별 정확도", ""]
    lines += [
        "| 레벨 | 건수 | MAE | MAPE | Bias | 전략진입율 | too_low | too_high | 샘플수(중간값) |",
        "|------|------|-----|------|------|----------|---------|---------|------------|",
    ]
    for lv, stats in sorted(fb_sections.items()):
        bias_sign = "+" if stats["bias"] >= 0 else ""
        lines.append(
            f"| {lv} | {stats['total']:,} | {stats['mae']:.6f} | "
            f"{stats['mape']:.4f}% | {bias_sign}{stats['bias']:.6f} | "
            f"{stats['in_range_agg']}% | {stats['too_low_pct']}% | {stats['too_high_pct']}% | "
            f"{stats['n_samples_median']}건 |"
        )
    lines.append("")

    # ── 샘플 충분성 ───────────────────────────────────────────
    if sample_buckets:
        lines += ["## 샘플 충분성 분석", ""]
        lines += [
            "> n_samples 구간별 성능 비교. MIN_SAMPLE_SIZE(현재 20) 기준의 적절성을 검증한다.",
            "",
            "| 구간 | 건수 | MAE | Hit Rate | Too Low | Too High |",
            "|------|------|-----|---------|---------|---------|",
        ]
        for sb in sample_buckets:
            lines.append(
                f"| {sb['label']} | {sb['n']:,} | {sb['mae']:.6f} | "
                f"**{sb['hit_rate']}%** | {sb['too_low_pct']}% | {sb['too_high_pct']}% |"
            )
        lines += ["", f"CLT 충족율 (n≥30): {overall['clt_pct']}% / 고신뢰 기준 (n≥50): {overall['high_conf_pct']}%", ""]

    # ── Offset Sweep ──────────────────────────────────────────
    if sweep:
        lines += _sweep_md_section(sweep)

    # ── KS test ───────────────────────────────────────────────
    if ks_results:
        lines += _ks_md_section(ks_results)

    # ── 결론 ──────────────────────────────────────────────────
    lines += ["## 결론", ""]

    # Bias 진단
    b = overall["bias"]
    if abs(b) < 0.001:
        lines.append("- **Bias**: 편향 없음 — 예측이 실제와 대체로 일치")
    elif b > 0:
        lines.append(f"- **Bias**: +{b:.4f} 과대예측 — 실제보다 높게 예측 → 투찰가가 낙찰선 위에 쌓임")
    else:
        lines.append(f"- **Bias**: {b:.4f} 과소예측 — 실제보다 낮게 예측 → 하한선 아래로 투찰될 위험")

    # 전략 vs 중립 비교
    diff = overall["in_range_agg"] - overall["in_range_neutral"]
    if diff < -5:
        lines.append(f"- **전략 효과**: aggressive(-MAD) 전략이 중립 대비 {abs(diff):.1f}%p 낮음 → 하한선 이탈 증가")
    elif diff > 5:
        lines.append(f"- **전략 효과**: aggressive(-MAD) 전략이 중립 대비 {diff:.1f}%p 높음")
    else:
        lines.append(f"- **전략 효과**: 중립 대비 {diff:+.1f}%p (유사)")

    # 실패 원인 진단
    tl = overall["too_low_pct"]
    th = overall["too_high_pct"]
    if tl > th * 2:
        lines.append(f"- **실패 원인**: too_low {tl}% >> too_high {th}% → offset이 너무 공격적, -MAD 완화 고려")
    elif th > tl * 2:
        lines.append(f"- **실패 원인**: too_high {th}% >> too_low {tl}% → predicted_rate 과대예측이 주원인")
    else:
        lines.append(f"- **실패 원인**: too_low {tl}% / too_high {th}% (균형적)")

    # MAD Calibration 진단
    cov1 = overall["mad_coverage"]
    cov2 = overall["mad_coverage_2x"]
    if cov1 < 40:
        lines.append(f"- **MAD 과소 추정**: ±1×MAD coverage {cov1}% (기대 50%) → -MAD offset이 예상보다 위험, ±2×MAD가 {cov2}% coverage")
    elif cov1 > 65:
        lines.append(f"- **MAD 과대 추정**: ±1×MAD coverage {cov1}% (기대 50%) → 불확실성을 보수적으로 추정 중, offset 확대 여지 있음")

    # 샘플-오차 상관 진단
    corr = overall["sample_error_corr"]
    if corr < -0.1:
        lines.append(f"- **샘플 효과 확인됨**: 상관 {corr:+.4f} → 샘플 많을수록 더 정확, MIN_SAMPLE_SIZE 기준 유효")
    elif corr > 0.1:
        lines.append(f"- **샘플 효과 없음**: 상관 {corr:+.4f} → 샘플 수가 정확도에 기여하지 않음, 데이터 품질 점검 필요")

    # 샘플 충분성 진단
    clt = overall["clt_pct"]
    hc  = overall["high_conf_pct"]
    if clt < 50:
        lines.append(f"- **샘플 부족 경고**: CLT 충족(n≥30) {clt}% — 절반 이상이 30건 미만, MIN_SAMPLE_SIZE 상향(30) 고려")
    elif hc < 30:
        lines.append(f"- **샘플 주의**: 고신뢰(n≥50) {hc}% — 데이터 누적 시 MIN_SAMPLE_SIZE 상향 여지 있음")
    else:
        lines.append(f"- **샘플 충분**: CLT 충족 {clt}% / 고신뢰 {hc}% — 현재 MIN_SAMPLE_SIZE=20 기준 적절")

    # n_samples 구간별 hit_rate 편차 — MIN_SAMPLE_SIZE 조정 근거
    if sample_buckets and len(sample_buckets) >= 2:
        min_hit = min(sb["hit_rate"] for sb in sample_buckets)
        max_hit = max(sb["hit_rate"] for sb in sample_buckets)
        if max_hit - min_hit > 10:
            best_sb = max(sample_buckets, key=lambda x: x["hit_rate"])
            lines.append(
                f"- **구간 편차 큼**: 샘플 구간별 hit_rate 차이 {max_hit - min_hit:.1f}%p "
                f"→ '{best_sb['label']}' 구간이 가장 우수, MIN_SAMPLE_SIZE 상향 시 성능 개선 기대"
            )

    # Skewness 진단
    sk = overall["skewness"]
    if sk > 1:
        lines.append(f"- **오차 분포**: Skewness +{sk:.2f} → 대부분 잘 맞지만 가끔 크게 빗나가는 케이스 존재")
    elif sk < -1:
        lines.append(f"- **오차 분포**: Skewness {sk:.2f} → 좌편향, 이상치 방향 확인 필요")

    # 공종별 강약
    weak   = [(t, s) for t, s in type_sections.items() if s and s["in_range_agg"] < 40]
    strong = [(t, s) for t, s in type_sections.items() if s and s["in_range_agg"] >= 60]
    if strong:
        lines.append("- **강한 공종**: " + ", ".join(f"{t}({s['in_range_agg']}%)" for t, s in strong))
    if weak:
        lines.append("- **취약 공종**: " + ", ".join(f"{t}({s['in_range_agg']}%)" for t, s in weak))

    # MAPE 경보
    if overall["mape"] > 1.0:
        lines.append(f"- **경고**: MAPE {overall['mape']:.2f}% — 1% 초과, 예측 신뢰도 낮음")
    elif overall["mape"] < 0.5:
        lines.append(f"- **양호**: MAPE {overall['mape']:.2f}% — 0.5% 미만, 예측 신뢰 가능")

    lines.append("")

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
    parser.add_argument(
        "--wf-months",
        type=int,
        default=6,
        help="Walk-Forward 검증 기간 (개월, 기본값: 6, 0이면 스킵)",
    )
    args = parser.parse_args()
    since = date.fromisoformat(args.since)

    print(f"백테스트 시작 — 검증셋: {since} 이후")
    results = await run_backtest(since)

    if not results:
        print("예측 가능한 레코드가 없습니다.")
        return

    sweep = run_offset_sweep(results)

    print("KS test: 학습셋 조회 중...")
    train_by_type = await fetch_train_rates(since)
    ks_results = run_ks_analysis(since, train_by_type, results)

    today_str = datetime.now().strftime("%Y%m%d")
    csv_path = Path(f"data/backtest_{today_str}.csv")
    md_path  = Path(f"data/backtest_{today_str}.md")

    save_csv(results, csv_path)
    save_md(results, md_path, since, ks_results, sweep)

    # Walk-Forward 검증
    if args.wf_months > 0:
        m = since.month - args.wf_months
        y = since.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        wf_start = date(y, m, 1)
        print(f"\nWalk-Forward 검증 시작 ({wf_start} ~ {since}, {args.wf_months}개월)")
        timeline = await run_walk_forward(wf_start, since)
        if timeline:
            wf_csv = Path(f"data/backtest_wf_{today_str}.csv")
            wf_md  = Path(f"data/backtest_wf_{today_str}.md")
            save_wf_csv(timeline, wf_csv)
            save_wf_md(timeline, wf_md, wf_start, since)

    total = len(results)
    overall = _section_stats(results)
    bias_dir = "과대" if overall["bias"] > 0 else "과소"
    print(f"\n{'='*55}")
    print(f"검증 건수         : {total:,}건")
    print(f"── 오차 지표 ──────────────────────────────")
    print(f"MAE (절대 오차)   : {overall['mae']:.6f}")
    print(f"MAPE (상대 오차)  : {overall['mape']:.4f}%")
    print(f"Bias (편향)       : {overall['bias']:+.6f} ({bias_dir}예측)")
    print(f"P25/P50/P75/P90   : {overall['p25_error']:.6f} / {overall['median_error']:.6f} / {overall['p75_error']:.6f} / {overall['p90_error']:.6f}")
    print(f"P95 오차          : {overall['p95_error']:.6f}")
    print(f"Skewness (왜도)   : {overall['skewness']:+.4f}")
    print(f"── 모델 성능 ──────────────────────────────")
    print(f"R² (결정계수)     : {overall['r_squared']:.4f}")
    print(f"Skill Score       : {overall['skill_score']:+.4f}")
    print(f"── 신뢰 구간 & 불확실성 ───────────────────")
    print(f"±0.5×MAD coverage : {overall['mad_coverage_half']:.1f}%  (기대 ~25%)")
    print(f"±1×MAD   coverage : {overall['mad_coverage']:.1f}%  (기대 ~50%)")
    print(f"±2×MAD   coverage : {overall['mad_coverage_2x']:.1f}%  (기대 ~75%)")
    print(f"±3×MAD   coverage : {overall['mad_coverage_3x']:.1f}%  (기대 ~90%)")
    print(f"샘플↔오차 상관    : {overall['sample_error_corr']:+.4f}")
    print(f"CLT 충족율 (n≥30) : {overall['clt_pct']:.1f}%")
    print(f"고신뢰 기준 (n≥50): {overall['high_conf_pct']:.1f}%")
    print(f"── 구간 진입 ──────────────────────────────")
    print(f"중립 진입율       : {overall['in_range_neutral']:.1f}%  (offset=0)")
    print(f"전략 진입율       : {overall['in_range_agg']:.1f}%  (offset=-MAD)")
    print(f"too_low / too_high: {overall['too_low_pct']:.1f}% / {overall['too_high_pct']:.1f}%")
    if overall["simulated_win_rate"] is not None:
        print(f"시뮬레이션 낙찰율  : {overall['simulated_win_rate']:.1f}%  (참여자 데이터 {overall['participant_coverage']:.1f}% 커버)")
    print(f"── 데이터 특성 ────────────────────────────")
    print(f"실제 사정률 평균  : {overall['actual_mean']:.6f} ± {overall['actual_std']:.6f}")
    print(f"샘플 수 중간값    : {overall['n_samples_median']}건  (범위: {overall['n_samples_min']}~{overall['n_samples_max']})")
    print(f"── Offset Sweep ───────────────────────────")
    best_sweep = max(sweep, key=lambda x: x["hit_rate"])
    for row in sweep:
        marker = "◀현재" if row["multiplier"] == 1.0 else ("★최적" if row["multiplier"] == best_sweep["multiplier"] and row["multiplier"] != 1.0 else "")
        print(f"  {row['label']:<12}: {row['hit_rate']:5.1f}%  too_low={row['too_low_pct']}%  {marker}")
    print(f"── KS test (분포 이동) ────────────────────────────")
    ks_overall = ks_results.get("overall")
    if ks_overall:
        drift_str = f"⚠ 이동 감지 ({ks_overall['severity']})" if ks_overall["drifted"] else "안정"
        print(f"전체 분포         : D={ks_overall['D']:.4f}  p={ks_overall['p_value']:.4f}  {drift_str}")
    for ptype, ks in sorted(ks_results.get("by_type", {}).items()):
        if ks is None:
            print(f"  {ptype:<12}: 샘플 부족")
            continue
        drift_str = f"⚠ 이동({ks['severity']})" if ks["drifted"] else "안정"
        print(f"  {ptype:<12}: D={ks['D']:.4f}  p={ks['p_value']:.4f}  {drift_str}")
    print(f"{'='*55}")


if __name__ == "__main__":
    asyncio.run(main())
