"""
scripts/validate_equilibrium.py
적격심사 투찰균형 이론의 예측을 실측 데이터로 검증한다.

근거 문헌:
  김도영(2020), "공공조달 적격심사제의 투찰균형", 재정학연구 13(3), pp.61-94.
  초록 요지 —
    (전제) 비가격요소 변별력이 없어 사실상 가격 단독 경쟁이다.
    (결론) 순수전략 균형은 없고 혼합전략 균형만 존재하며,
           그 균형에서 입찰자들은 "일정 수준 이하의 낙찰하한가는 배제하고" 투찰한다.

검증 항목:
  [전제] 낙찰자 = 하한 이상 최저가인가?
         깨지면 적격심사 탈락이 실재한다는 뜻이고, 그러면 히스토그램의
         win_count 는 "낙찰 빈도"가 아니라 "최저가 도달 빈도"가 된다.
  [가설] offset 분포에 하단 절단선이 있는가?
         있으면 그 값이 히스토그램 x축 하한이 된다.
  [부수] offset 이 이산 격자 위에 놓이는가?
         distribution.py 의 _BIN_PCT_RESOLUTION(0.1%) 이 적정한지 판단한다.

사용법:
  python scripts/validate_equilibrium.py

읽기 전용이다. 아무것도 쓰지 않는다.
"""

import asyncio
import io
import os
import sys
from collections import Counter

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncpg

DB_URL = os.getenv("DATABASE_URL", "postgresql://postgres@localhost:5432/gonggong").replace(
    "postgresql+asyncpg://", "postgresql://"
)

# app/db/crud.py 의 TARGET_BID_TYPE / TARGET_PRICE_METHOD 와 같은 값.
# '기타' 허용은 crud_distribution._target_filters() 의 임시 완화와 동일하다 (T-001).
TARGET_BID_TYPE = "적격심사"
TARGET_PRICE_METHOD = "복수예비가격"

_WHERE = """
      (h.bid_type = $1 OR h.bid_type = '기타')
  AND (h.price_method = $2 OR h.price_method = '기타')
"""

# 운영 경로(crud_distribution)와 동일하게 legal 이 없으면 lower_limit_rate 로 폴백한다.
_LIMIT_EXPR = "COALESCE(h.legal_limit_rate, h.lower_limit_rate)"

# offset 집계 해상도 (% 단위 소수점 자릿수). 3 = 0.001%
_MILLI = 3


def _q_notices(exclude: bool) -> str:
    """
    공고별 낙찰자 위치 집계.

    exclude=True 면 낙찰자 불변식이 깨진 공고(= 하한율 오염분)를 제외한다.
    처음에는 `legal_limit_rate IS NOT NULL` 로 걸렀는데, 마이그레이션
    d5c7b39a4e10 이 전 행에 legal 을 채워놔서 아무것도 걸러지지 않았다.
    실제로 믿을 수 없는 건 "NULL 인 행"이 아니라 "낙찰자가 하한 아래인 공고"다.
    """
    extra = " AND p.project_id <> ALL($3::text[])" if exclude else ""
    return f"""
    WITH q AS (
        SELECT p.project_id, p.bid_rate, p.is_winner, {_LIMIT_EXPR} AS lim
        FROM bid_participants p
        JOIN bids_history h ON p.project_id = h.project_id
        WHERE {_WHERE} {extra}
    ),
    w AS (
        SELECT project_id, MIN(bid_rate) AS winner_rate
        FROM q WHERE is_winner GROUP BY project_id
    )
    SELECT q.project_id,
           MIN(q.lim)            AS lim,
           MIN(w.winner_rate)    AS winner_rate,
           COUNT(*)              AS n_all,
           COUNT(*) FILTER (WHERE q.bid_rate >= q.lim) AS n_valid,
           COUNT(*) FILTER (WHERE q.bid_rate >= q.lim
                              AND q.bid_rate <  w.winner_rate) AS n_below
    FROM q LEFT JOIN w ON w.project_id = q.project_id
    GROUP BY q.project_id
    """


def _q_bins(exclude: bool) -> str:
    """offset(%) 을 0.001% 해상도로 집계."""
    extra = " AND p.project_id <> ALL($3::text[])" if exclude else ""
    return f"""
    SELECT ROUND((p.bid_rate - {_LIMIT_EXPR}) * 100, {_MILLI}) AS off_pct,
           COUNT(*) AS cnt
    FROM bid_participants p
    JOIN bids_history h ON p.project_id = h.project_id
    WHERE {_WHERE} {extra}
    GROUP BY 1
    ORDER BY 1
    """


# ── 공통 계산 ────────────────────────────────────────────────────────────


def _cum_offset(bins: list[tuple[float, int]], total: int, frac: float) -> float | None:
    """누적 비율 frac 에 처음 도달하는 offset 을 반환한다."""
    if total == 0:
        return None
    need = total * frac
    acc = 0
    for off, cnt in bins:
        acc += cnt
        if acc >= need:
            return off
    return bins[-1][0]


def _fmt(v: float | None, unit: str = "%p") -> str:
    return "n/a" if v is None else f"{v:+.3f}{unit}"


# ── [전제] 낙찰자 = 하한 이상 최저가인가 ────────────────────────────────


def check_lowest_wins(rows) -> dict:
    total = len(rows)
    no_winner = [r for r in rows if r["winner_rate"] is None]
    violation = [
        r for r in rows if r["winner_rate"] is not None and r["winner_rate"] < r["lim"]
    ]
    clean = [
        r for r in rows if r["winner_rate"] is not None and r["winner_rate"] >= r["lim"]
    ]
    hit = [r for r in clean if r["n_below"] == 0]
    gap = Counter(min(r["n_below"], 4) for r in clean if r["n_below"] > 0)

    return {
        "total": total,
        "no_winner": len(no_winner),
        "violation": len(violation),
        "clean": len(clean),
        "hit": len(hit),
        "hit_pct": len(hit) / len(clean) * 100 if clean else 0.0,
        "gap": gap,
        "bad_ids": [r["project_id"] for r in violation],
    }


def print_lowest_wins(s: dict) -> str:
    print("\n" + "-" * 62)
    print("  [전제] 낙찰자 = 하한 이상 최저가인가")
    print("-" * 62)
    print(f"  참여자가 있는 공고         : {s['total']:,}건")
    print(f"  낙찰자 행 없음 (분석 제외) : {s['no_winner']:,}건")
    print(f"  낙찰자 < 법정하한 (오염)   : {s['violation']:,}건   <- T-010")
    print(f"  분석 대상                  : {s['clean']:,}건")
    print()
    print(f"  최저가 낙찰 성립 : {s['hit']:,}건 / {s['clean']:,}건 = {s['hit_pct']:.1f}%")

    if s["gap"]:
        print("\n  미성립 공고 - 낙찰자보다 싸게 넣고도 떨어진 업체 수:")
        for k in sorted(s["gap"]):
            label = "4명 이상" if k == 4 else f"{k}명"
            print(f"    {label:>8} : {s['gap'][k]:,}건")

    if s["clean"] == 0:
        verdict = "n/a"
        print("\n  -> 분석 대상이 없다.")
    elif s["hit_pct"] >= 95:
        verdict = "ok"
        print("\n  -> 전제 성립. 가격 단독 경쟁으로 봐도 된다.")
        print("     win_count 를 '낙찰 빈도'로 읽어도 무방하다.")
    elif s["hit_pct"] >= 85:
        verdict = "warn"
        print("\n  -> 대체로 성립하나 예외가 있다. 적격심사 탈락이 섞여 있을 수 있다.")
    else:
        verdict = "fail"
        print("\n  -> 전제 의심. 최저가가 낙찰되지 않는 공고가 많다.")
        print("     win_count 는 '낙찰 빈도'가 아니라 '최저가 도달 빈도'에 가깝다.")
    return verdict


# ── [가설] 하단 절단선 ──────────────────────────────────────────────────

_MARKS = (0.001, 0.005, 0.01, 0.05, 0.10, 0.25, 0.50)

# 분포 시작점이 이 값 이하면 "법정 하한에서 바로 시작" = 전략적 절단선이 아니다.
_FLOOR_EPS = 0.05  # %p


def check_threshold(bins: list[tuple[float, int]]) -> dict:
    total = sum(c for _, c in bins)
    neg = sum(c for o, c in bins if o < 0)
    pos = [(o, c) for o, c in bins if o >= 0]
    pos_total = sum(c for _, c in pos)

    marks = {f: _cum_offset(pos, pos_total, f) for f in _MARKS}
    p001, p05 = marks[0.001], marks[0.05]
    width = None if p001 is None or p05 is None else p05 - p001

    # 0.1% 해상도로 재집계 (distribution.py 와 같은 bin)
    deci: Counter = Counter()
    for o, c in pos:
        deci[round(o, 1)] += c

    deci_sorted = sorted(deci.items())
    floor_share = (
        deci_sorted[0][1] / pos_total * 100 if deci_sorted and pos_total else 0.0
    )

    return {
        "total": total,
        "neg": neg,
        "neg_pct": neg / total * 100 if total else 0.0,
        "pos_total": pos_total,
        "marks": marks,
        "width": width,
        "deci": deci_sorted,
        "floor_share": floor_share,
    }


def print_threshold(s: dict, bottom: int = 12) -> str:
    print("\n" + "-" * 62)
    print("  [가설] offset 분포에 하단 절단선이 있는가")
    print("-" * 62)
    print(f"  전체 투찰 행            : {s['total']:,}건")
    print(f"  offset < 0 (하한 미달)  : {s['neg']:,}건 ({s['neg_pct']:.2f}%)")
    if s["neg_pct"] >= 1:
        print("    ! 하한 미달은 실격이라 원래 존재할 수 없다. 하한율 오염 신호다.")
    print(f"  분석 대상 (offset >= 0) : {s['pos_total']:,}건")

    print("\n  누적 분위:")
    for f in _MARKS:
        print(f"    P{f*100:>6.1f}%  ->  offset {_fmt(s['marks'][f])}")

    print(f"\n  하단 폭 (P5 - P0.1) : {_fmt(s['width'])}")

    print(f"\n  최하단 {bottom}개 bin (0.1% 해상도, distribution.py 와 동일):")
    print("    offset      건수      누적%")
    acc = 0
    for off, cnt in s["deci"][:bottom]:
        acc += cnt
        share = acc / s["pos_total"] * 100 if s["pos_total"] else 0
        print(f"    {off:+6.1f}%  {cnt:>8,}   {share:>7.3f}%")

    w = s["width"]
    floor = s["marks"][0.001]

    # 판정에는 두 값이 다 필요하다.
    #   floor : 분포가 시작되는 지점. 논문이 말한 "배제되는 수준"의 상한이다.
    #   w     : 그 지점에서 얼마나 가파르게 솟는가.
    # w 만 보면 "법정 하한에 다들 딱 붙어 있는" 상태도 절단선으로 오판한다.
    # 그건 절단이 아니라 반대로 하한에 몰리는 것이다.
    if w is None or floor is None:
        verdict = "n/a"
        print("\n  -> 판정 불가.")
    elif floor <= _FLOOR_EPS:
        verdict = "fail"
        print(f"\n  -> 논문 예측과 불일치. 분포가 법정 하한({_fmt(floor)})에서 바로 시작한다.")
        print(f"     최하단 bin(+0.0%)에만 이미 {s['floor_share']:.1f}% 가 들어 있다.")
        print("     '일정 수준 이하를 배제'하는 게 아니라 하한선에 몰려 있다.")
        print("     x축을 잘라낼 여지가 없다 — 하한이 곧 최빈 구간의 시작이다.")
    elif w <= 0.2:
        verdict = "ok"
        print(f"\n  -> 뚜렷한 절단선. 분포가 {_fmt(floor)} 에서 시작해 {w:.3f}%p 만에 솟는다.")
        print("     그 아래는 사실상 아무도 가지 않는다. x축 하한으로 쓸 수 있다.")
    else:
        verdict = "warn"
        print(f"\n  -> 약한 절단. 시작점 {_fmt(floor)}, 하위 5% 폭 {w:.3f}%p.")
        print("     축을 자르기엔 근거가 약하다.")
    return verdict


# ── [부수] bin 해상도 점검 ──────────────────────────────────────────────


def print_lattice(bins: list[tuple[float, int]], top: int = 12) -> None:
    pos = [(o, c) for o, c in bins if o >= 0]
    total = sum(c for _, c in pos)
    if total == 0:
        return

    print("\n" + "-" * 62)
    print("  [부수] offset 이 이산 격자 위에 놓이는가 (bin 해상도 점검)")
    print("-" * 62)
    print(f"  서로 다른 offset 값 (0.001% 해상도) : {len(pos):,}개")

    # 0.1% 배수에 정확히 걸리는 비중
    on_grid = sum(c for o, c in pos if abs(o * 10 - round(o * 10)) < 1e-9)
    print(f"  0.1% 격자에 정확히 걸리는 비중      : {on_grid/total*100:.1f}%")

    print(f"\n  최빈 offset {top}개:")
    for off, cnt in sorted(pos, key=lambda x: -x[1])[:top]:
        print(f"    {off:+8.3f}%  {cnt:>8,}  ({cnt/total*100:.2f}%)")

    if on_grid / total >= 0.95:
        print("\n  -> 투찰율이 0.1% 격자 위에 놓인다. _BIN_PCT_RESOLUTION=1 이 적정하다.")
    elif len(pos) / total >= 0.5:
        print("\n  -> 값이 거의 전부 제각각이다. 격자가 없거나 해상도가 더 잘다.")
        print("     0.1% bin 이 실제 구조를 뭉개고 있는지 확인이 필요하다.")
    else:
        print("\n  -> 부분적으로 뭉친다. 최빈값 간격을 보고 bin 해상도를 정하면 된다.")


# ── 오염 영향 교차 점검 ─────────────────────────────────────────────────


def print_contamination(l_thr: dict, c_thr: dict, n_bad: int) -> None:
    print("\n" + "-" * 62)
    print("  [교차] 하한율 오염이 분포 하단을 얼마나 흔드는가")
    print("-" * 62)
    print("  전체     = 앱이 지금 그리는 분포 그대로")
    print(f"  오염 제외 = 낙찰자 불변식이 깨진 공고 {n_bad}건을 통째로 뺀 분포\n")
    rows = [
        ("투찰 행 수", f"{l_thr['total']:,}", f"{c_thr['total']:,}"),
        ("하한 미달 비중", f"{l_thr['neg_pct']:.2f}%", f"{c_thr['neg_pct']:.2f}%"),
        ("분포 시작점 P0.1", _fmt(l_thr["marks"][0.001]), _fmt(c_thr["marks"][0.001])),
        ("하단 폭 (P5-P0.1)", _fmt(l_thr["width"]), _fmt(c_thr["width"])),
        ("최하단 bin 비중", f"{l_thr['floor_share']:.1f}%", f"{c_thr['floor_share']:.1f}%"),
    ]
    print(f"    {'항목':<20}{'전체':>14}{'오염 제외':>14}")
    print("    " + "-" * 48)
    for label, a, b in rows:
        print(f"    {label:<20}{a:>14}{b:>14}")

    if c_thr["neg_pct"] >= 1.0:
        print("\n  ! 오염 공고를 빼도 하한 미달이 남는다. 불변식이 안 잡아내는 오염이 더 있다.")
    else:
        print("\n  오염 공고를 빼면 하한 미달이 사라진다. 불변식이 오염을 제대로 집어낸다.")


# ── main ────────────────────────────────────────────────────────────────


async def load(conn, exclude_ids: list[str] | None = None):
    args = [TARGET_BID_TYPE, TARGET_PRICE_METHOD]
    if exclude_ids is not None:
        args.append(exclude_ids)
    use_exclude = exclude_ids is not None
    notices = await conn.fetch(_q_notices(use_exclude), *args)
    raw = await conn.fetch(_q_bins(use_exclude), *args)
    bins = [(float(r["off_pct"]), r["cnt"]) for r in raw if r["off_pct"] is not None]
    return notices, bins


async def main():
    conn = await asyncpg.connect(DB_URL)
    try:
        print("=" * 62)
        print("  적격심사 투찰균형 검증  (김도영 2020, 재정학연구 13-3)")
        print("=" * 62)

        loose_rows, loose_bins = await load(conn)
        if not loose_rows:
            print("\n[FAIL] 대상 데이터가 없다. bid_participants 적재를 먼저 확인하라.")
            return

        loose = check_lowest_wins(loose_rows)
        v1 = print_lowest_wins(loose)

        l_thr = check_threshold(loose_bins)
        v2 = print_threshold(l_thr)

        print_lattice(loose_bins)

        bad = loose["bad_ids"]
        if bad:
            _, clean_bins = await load(conn, exclude_ids=bad)
            print_contamination(l_thr, check_threshold(clean_bins), len(bad))
        else:
            print("\n  (오염 공고가 없어 교차 점검을 건너뛴다)")

        print("\n" + "=" * 62)
        print(f"  전제(최저가 낙찰) : {v1.upper()}")
        print(f"  가설(하단 절단선) : {v2.upper()}")
        print("=" * 62)
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    asyncio.run(main())
