"""
분포 엔진(distribution engine) 백테스트.

예측 엔진 백테스트(backtest.py)가 "사정률 점 예측"의 MAE/R²를 재는 것과 달리,
이 스크립트는 분포 엔진이 보여주는 것들이 미래에도 유효한지를 검증한다.

학습셋: cutoff 이전 / 검증셋: cutoff 이후 (기본 2025-01-01)
누출 방지: 학습 분포는 cutoff 이전 데이터만으로 구성.

측정 항목:
  ① 낙찰자 offset 안정성  — 학습 분포가 검증 낙찰자 위치를 대표하나 (median 이동, KS)
  ② win_rate 캘리브레이션 — 화면에 띄우는 "과거 낙찰빈도"가 out-of-sample에서 맞나
  ③ 밴드 적중률           — 학습으로 그은 타깃 밴드에 검증 낙찰자가 든 비율 (밴드폭 sweep)

offset 정의는 app/engine/distribution.py 와 동일: offset = (투찰율 − 낙찰하한율) × 100, 0.1% 반올림.

사용법:
  python scripts/backtest_distribution.py
  python scripts/backtest_distribution.py --cutoff 2025-01-01
"""

import argparse
import io
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Windows 터미널 UTF-8 출력 강제 (backtest.py와 동일)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from scipy.stats import ks_2samp, spearmanr

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gonggong.db"

# 엔진 필터(crud_distribution._RELAX_FILTERS)와 동일
_RELAX_WHERE = """
    b.bid_type IN ('적격심사', '기타')
    AND b.price_method IN ('복수예비가격', '기타')
"""

# 캘리브레이션·밴드를 보는 의미있는 구간 (낙찰이 실제로 일어나는 영역)
ACTION_LO, ACTION_HI = -1.5, 0.5


# ── 데이터 로드 ────────────────────────────────────────────────────────────

def load_rows(con: sqlite3.Connection, cutoff: str, clip: float):
    """
    참여자 offset 행을 (train, test)로 분리해 반환.
    각 행: (offset_pct[0.1%반올림], is_winner[0/1], project_id)
    """
    sql = f"""
        SELECT b.bid_date,
               ROUND((p.bid_rate - b.lower_limit_rate) * 100, 1) AS off_pct,
               p.is_winner,
               p.project_id
        FROM bid_participants p
        JOIN bids_history b ON p.project_id = b.project_id
        WHERE b.bid_date IS NOT NULL
          AND p.bid_rate IS NOT NULL
          AND b.lower_limit_rate IS NOT NULL
          AND {_RELAX_WHERE}
    """
    train, test = [], []
    for bid_date, off, win, pid in con.execute(sql):
        if off is None or abs(off) > clip:
            continue
        rec = (off, int(win or 0), pid)
        (test if str(bid_date) >= cutoff else train).append(rec)
    return train, test


def primary_types(con: sqlite3.Connection) -> dict:
    """project_id → 대표 공종. 비상호허용(is_mutual=0) 우선, 없으면 첫 번째 (backtest.py와 동일 규칙)."""
    rows = con.execute(
        "SELECT project_id, type_name, is_mutual, id FROM bid_license_types ORDER BY id"
    ).fetchall()
    best: dict = {}
    for pid, tname, is_mutual, _id in rows:
        cur = best.get(pid)
        # 우선순위: 비상호허용 > 상호허용. 같은 등급이면 먼저 온 것 유지.
        if cur is None:
            best[pid] = (tname, is_mutual)
        elif cur[1] and not is_mutual:  # 기존이 상호허용인데 새 것이 비상호허용
            best[pid] = (tname, is_mutual)
    return {pid: t for pid, (t, _) in best.items()}


# ── 통계 헬퍼 ──────────────────────────────────────────────────────────────

def _quantile(sorted_xs: list, q: float) -> float:
    if not sorted_xs:
        return 0.0
    idx = min(int(len(sorted_xs) * q), len(sorted_xs) - 1)
    return sorted_xs[idx]


def offset_summary(offsets: list) -> dict:
    xs = sorted(offsets)
    n = len(xs)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "median": statistics.median(xs),
        "mean": statistics.mean(xs),
        "q1": _quantile(xs, 0.25),
        "q3": _quantile(xs, 0.75),
    }


# ── ① 낙찰자 offset 안정성 ──────────────────────────────────────────────────

def section_stability(train, test, ptypes):
    tr_win = [o for o, w, _ in train if w]
    te_win = [o for o, w, _ in test if w]
    tr = offset_summary(tr_win)
    te = offset_summary(te_win)
    ks_d, ks_p = ks_2samp(tr_win, te_win)

    # 공종별
    def by_type(rows):
        d = defaultdict(list)
        for o, w, pid in rows:
            if w:
                d[ptypes.get(pid, "기타")].append(o)
        return d

    tr_by = by_type(train)
    te_by = by_type(test)
    per_type = []
    for t in sorted(set(tr_by) & set(te_by)):
        if len(tr_by[t]) < 100 or len(te_by[t]) < 100:
            continue
        s_tr = offset_summary(tr_by[t])
        s_te = offset_summary(te_by[t])
        d, p = ks_2samp(tr_by[t], te_by[t])
        per_type.append((t, s_tr, s_te, d, p))

    return {"train": tr, "test": te, "ks_d": ks_d, "ks_p": ks_p, "per_type": per_type}


# ── ② win_rate 캘리브레이션 ─────────────────────────────────────────────────

def bin_win_rates(rows, lo, hi):
    """offset bin별 (count, win) 집계. action zone 안만."""
    agg = defaultdict(lambda: [0, 0])  # bin → [count, win]
    for o, w, _ in rows:
        if lo <= o <= hi:
            agg[round(o, 1)][0] += 1
            agg[round(o, 1)][1] += w
    return agg


def section_calibration(train, test, min_bin):
    tr = bin_win_rates(train, ACTION_LO, ACTION_HI)
    te = bin_win_rates(test, ACTION_LO, ACTION_HI)

    bins = []
    for b in sorted(set(tr) & set(te)):
        tr_c, tr_w = tr[b]
        te_c, te_w = te[b]
        if tr_c < min_bin or te_c < min_bin:
            continue
        pred = tr_w / tr_c * 100
        actual = te_w / te_c * 100
        bins.append({"bin": b, "pred": pred, "actual": actual, "te_count": te_c, "tr_count": tr_c})

    if not bins:
        return {"bins": [], "wmae": None, "spearman": None}

    total_w = sum(x["te_count"] for x in bins)
    wmae = sum(x["te_count"] * abs(x["pred"] - x["actual"]) for x in bins) / total_w
    rho = spearmanr([x["pred"] for x in bins], [x["actual"] for x in bins]).correlation if len(bins) >= 3 else None
    return {"bins": bins, "wmae": wmae, "spearman": rho}


# ── ③ 밴드 적중률 ────────────────────────────────────────────────────────────

BAND_WIDTHS = [0.1, 0.15, 0.2, 0.3, 0.5]


def section_band(stab, test):
    te_win = [o for o, w, _ in test if w]
    n = len(te_win)
    m = stab["train"]["median"]
    q1, q3 = stab["train"]["q1"], stab["train"]["q3"]

    rows = []
    # IQR 밴드
    iqr_hit = sum(1 for o in te_win if q1 <= o <= q3) / n * 100
    rows.append({"label": f"학습 IQR [{q1:+.2f}, {q3:+.2f}]", "width": q3 - q1, "hit": iqr_hit})
    # median ± w 밴드 sweep
    for w in BAND_WIDTHS:
        hit = sum(1 for o in te_win if m - w <= o <= m + w) / n * 100
        rows.append({"label": f"median {m:+.2f} ± {w}", "width": 2 * w, "hit": hit})
    return {"median": m, "rows": rows, "n": n}


# ── ④ fallback 레벨 효용 ────────────────────────────────────────────────────

_MIN_DIST = 200  # 엔진 _MIN_DIST_SAMPLE 과 동일 (레벨 채택 최소 참여자 행수)
_BAND_W = 0.3    # median ± _BAND_W 밴드 (③에서 검증 낙찰자 ~69% 포함하던 폭)


def bucket_of(bp) -> int:
    """base_price → bucket_id. crud._BUCKET_RANGES 와 동일 경계."""
    if bp is None:
        return 0
    if bp < 100_000_000:
        return 1
    if bp < 500_000_000:
        return 2
    if bp < 2_000_000_000:
        return 3
    return 4


def load_projects(con: sqlite3.Connection, cutoff: str, clip: float):
    """
    공고 단위로 메타 + 참여자 집계를 만들어 (train, test) dict 로 분리.
    각 공고: client(=client_id or name), region, bucket, types(set), ptype(대표공종),
             n(참여자 행수), woffs(낙찰자 offset 리스트).
    멀티공종은 각 type 그룹에 공고를 넣어 엔진(type_name 단일 필터)을 재현한다.
    global 중복을 피하려 참여자 집계는 license JOIN 없이 공고당 1세트로만 한다.
    """
    # 1) 공고당 참여자 행수 + 낙찰자 offset (license JOIN 없음)
    part = defaultdict(lambda: [0, []])  # pid -> [n_part, [win_off...]]
    sql_p = f"""
        SELECT b.project_id,
               ROUND((p.bid_rate - b.lower_limit_rate) * 100, 1),
               p.is_winner
        FROM bid_participants p
        JOIN bids_history b ON p.project_id = b.project_id
        WHERE p.bid_rate IS NOT NULL
          AND b.lower_limit_rate IS NOT NULL
          AND b.bid_date IS NOT NULL
          AND {_RELAX_WHERE}
    """
    for pid, off, win in con.execute(sql_p):
        if off is None or abs(off) > clip:
            continue
        part[pid][0] += 1
        if win:
            part[pid][1].append(off)

    # 2) 공종 (멀티 set + 대표 1개; primary_types 와 동일 규칙)
    types_by, prim_by = {}, {}
    for pid, tname, is_mut, _id in con.execute(
        "SELECT project_id, type_name, is_mutual, id FROM bid_license_types ORDER BY id"
    ):
        types_by.setdefault(pid, set()).add(tname)
        cur = prim_by.get(pid)
        if cur is None:
            prim_by[pid] = (tname, is_mut)
        elif cur[1] and not is_mut:  # 기존 상호허용 → 새 비상호허용으로 교체
            prim_by[pid] = (tname, is_mut)

    # 3) 메타 + 조립 + train/test 분리
    train, test = {}, {}
    sql_m = f"""
        SELECT b.project_id, b.client_id, b.client_name, b.region, b.base_price, b.bid_date
        FROM bids_history b
        WHERE b.bid_date IS NOT NULL AND {_RELAX_WHERE}
    """
    for pid, cid, cname, reg, bp, bdate in con.execute(sql_m):
        if pid not in part:
            continue
        n, woffs = part[pid]
        # client_id 컬럼은 전부 'None' 문자열(ETL 미적재)이라 변별 불가 → client_name 사용
        rec = {
            "client": cname or "",
            "region": reg or "",
            "bucket": bucket_of(bp),
            "types": types_by.get(pid, set()),
            "ptype": prim_by.get(pid, ("기타", 0))[0],
            "n": n,
            "woffs": woffs,
        }
        (test if str(bdate) >= cutoff else train)[pid] = rec
    return train, test


def section_fallback(train: dict, test: dict):
    """fallback 레벨별 효용. (A) 레벨 격리 비교 + (B) 정책 vs global."""
    # 학습 인덱스: (type,bucket) / (client,type,bucket) → [pid], 그리고 global 풀
    tb_idx, cl_idx = defaultdict(list), defaultdict(list)
    g_n, g_offs = 0, []
    for pid, r in train.items():
        g_n += r["n"]
        g_offs += r["woffs"]
        for t in r["types"]:
            tb_idx[(t, r["bucket"])].append(pid)
            cl_idx[(r["client"], t, r["bucket"])].append(pid)
    g_offs.sort()
    g_ok = g_n >= _MIN_DIST and bool(g_offs)

    def pool(pids):
        n, offs = 0, []
        for p in pids:
            n += train[p]["n"]
            offs += train[p]["woffs"]
        offs.sort()
        return n, offs, len(pids)

    def stat(offs, w):
        m = statistics.median(offs)
        q1, q3 = _quantile(offs, 0.25), _quantile(offs, 0.75)
        hit = 1.0 if (m - _BAND_W <= w <= m + _BAND_W) else 0.0
        return hit, abs(w - m), (q3 - q1), m

    levels = ("client", "region", "type_bucket")
    acc = {l: defaultdict(float) for l in levels}    # 레벨 자신
    accg = {l: defaultdict(float) for l in levels}   # 같은 공고에서의 global
    pol = defaultdict(float)
    chose = defaultdict(int)
    n_eval = 0

    for pid, v in test.items():
        if not v["woffs"]:  # 낙찰자 offset 없는 공고는 평가 대상 아님
            continue
        w = statistics.median(v["woffs"])
        tb_pids = tb_idx.get((v["ptype"], v["bucket"]), [])
        cl_pids = cl_idx.get((v["client"], v["ptype"], v["bucket"]), [])
        # region: 엔진과 동일하게 '전국' OR (검증공고 region 이 학습 region 의 substring)
        rg_pids = [
            p for p in tb_pids
            if train[p]["region"] == "전국" or (v["region"] and v["region"] in train[p]["region"])
        ]
        cand = {}
        for lvl, pids in (("client", cl_pids), ("region", rg_pids), ("type_bucket", tb_pids)):
            n, offs, cnt = pool(pids)
            if n >= _MIN_DIST and offs:
                cand[lvl] = (n, offs, cnt)

        if not g_ok:
            continue
        n_eval += 1
        gh, gd, _, _ = stat(g_offs, w)

        # (A) 레벨 격리 — 그 레벨이 가능한 공고에서만, 같은 공고 global 과 짝지어 비교
        for lvl in levels:
            if lvl in cand:
                _, offs, cnt = cand[lvl]
                h, d, iqr, _ = stat(offs, w)
                a = acc[lvl]
                a["hit"] += h; a["dist"] += d; a["iqr"] += iqr; a["cnt"] += cnt; a["n"] += 1
                ag = accg[lvl]
                ag["hit"] += gh; ag["dist"] += gd

        # (B) 정책 — 실제 fallback 이 고르는 가용 최상위 레벨
        sel = next((l for l in ("client", "region", "type_bucket") if l in cand), "global")
        chose[sel] += 1
        offs = g_offs if sel == "global" else cand[sel][1]
        h, _, _, _ = stat(offs, w)
        pol["policy"] += h
        pol["global"] += gh

    return {"n_eval": n_eval, "acc": acc, "accg": accg, "pol": pol, "chose": chose, "levels": levels}


def build_fallback_report(fb: dict) -> str:
    L = ["\n── ④ fallback 레벨 효용 (밴드 median ± {:.1f}%p) ─────────".format(_BAND_W)]
    N = fb["n_eval"]
    if N == 0:
        L.append("  global 분포 표본 부족 — 평가 불가")
        return "\n".join(L)
    L.append(f"  평가 공고(검증, 낙찰자 보유): {N:,}")
    L.append("\n  [A] 레벨 격리 — 그 레벨이 가능한 공고에서  vs  같은 공고의 global")
    L.append("  레벨        | 커버  | 적중 레벨/글로벌 | 거리MAE 레벨/글로벌 | IQR폭 | 기여공고")
    L.append("  " + "-" * 74)
    for lvl in fb["levels"]:
        a, ag = fb["acc"][lvl], fb["accg"][lvl]
        n = int(a["n"])
        if n == 0:
            L.append(f"  {lvl:<11} | 가용 공고 없음")
            continue
        L.append(
            f"  {lvl:<11} | {n / N * 100:4.1f}% | "
            f"{a['hit'] / n * 100:5.1f} / {ag['hit'] / n * 100:5.1f}% | "
            f"{a['dist'] / n:6.3f} / {ag['dist'] / n:6.3f} | "
            f"{a['iqr'] / n:5.3f} | {a['cnt'] / n:5.1f}"
        )
    L.append("\n  [B] 실제 fallback 정책  vs  무조건 global (전체 평가 공고)")
    L.append(f"  정책 적중 : {fb['pol']['policy'] / N * 100:5.1f}%    global 적중 : {fb['pol']['global'] / N * 100:5.1f}%")
    sel = fb["chose"]
    seltxt = "  ".join(
        f"{k}:{sel[k]}({sel[k] / N * 100:.0f}%)"
        for k in ("client", "region", "type_bucket", "global") if sel.get(k)
    )
    L.append(f"  레벨 선택 분포 : {seltxt}")
    L.append("\n  · 거리MAE=|낙찰자offset − 분포median|, 낮을수록 자리 정확. IQR폭 좁을수록 신호 또렷.")
    L.append("  · 기여공고=레벨 분포를 만든 distinct 공고 수. 1~2면 200참여자라도 단일공고라 신뢰 낮음.")
    L.append("  · region: 학습의 80%가 '전국'이라 region 레벨은 구조적으로 global 에 수렴할 수 있음.")
    return "\n".join(L)


# ── 리포트 ────────────────────────────────────────────────────────────────

def build_report(cutoff, stab, calib, band):
    L = []
    tr, te = stab["train"], stab["test"]

    L.append("=" * 60)
    L.append(f"분포 엔진 백테스트 — 학습 < {cutoff} ≤ 검증")
    L.append("=" * 60)

    L.append("\n── ① 낙찰자 offset 안정성 ───────────────────────────")
    L.append(f"학습 낙찰자 : n={tr['n']:,}  median={tr['median']:+.2f}%  IQR=[{tr['q1']:+.2f}, {tr['q3']:+.2f}]  mean={tr['mean']:+.2f}")
    L.append(f"검증 낙찰자 : n={te['n']:,}  median={te['median']:+.2f}%  IQR=[{te['q1']:+.2f}, {te['q3']:+.2f}]  mean={te['mean']:+.2f}")
    L.append(f"중앙값 이동  : {te['median'] - tr['median']:+.3f}%p")
    sev = "안정" if stab["ks_d"] < 0.1 else ("주의" if stab["ks_d"] < 0.2 else "심각")
    L.append(f"KS test     : D={stab['ks_d']:.4f}  p={stab['ks_p']:.4f}  → 분포 일치도 {sev}")
    if stab["per_type"]:
        L.append("\n  [공종별] (학습 median → 검증 median / 이동 / KS D)")
        for t, s_tr, s_te, d, p in stab["per_type"]:
            L.append(f"   {t:<10}: {s_tr['median']:+.2f}% → {s_te['median']:+.2f}%  ({s_te['median']-s_tr['median']:+.3f}%p)  D={d:.3f}")

    L.append("\n── ② win_rate 캘리브레이션 (action zone {:.1f}~{:.1f}%) ──".format(ACTION_LO, ACTION_HI))
    if calib["wmae"] is None:
        L.append("  표본 부족 — bin별 비교 불가")
    else:
        L.append(f"가중 캘리브레이션 오차(wMAE) : {calib['wmae']:.3f}%p  (예측 win_rate vs 실제 win_rate)")
        if calib["spearman"] is not None:
            L.append(f"순위 상관(Spearman)         : {calib['spearman']:+.3f}  (예측이 높은 bin이 실제도 높은가)")
        L.append("\n  bin offset | 예측 win% | 실제 win% | 오차 | 검증N")
        L.append("  " + "-" * 52)
        for x in sorted(calib["bins"], key=lambda x: x["te_count"], reverse=True)[:10]:
            L.append(f"  {x['bin']:+6.1f}%   | {x['pred']:7.2f}  | {x['actual']:7.2f}  | {abs(x['pred']-x['actual']):4.2f} | {x['te_count']:,}")

    L.append("\n── ③ 밴드 적중률 (검증 낙찰자 N={:,}) ──────────────".format(band["n"]))
    L.append("  밴드 정의                       | 폭(%p) | 적중률")
    L.append("  " + "-" * 52)
    for r in band["rows"]:
        L.append(f"  {r['label']:<30} | {r['width']:5.2f}  | {r['hit']:5.1f}%")

    L.append("\n── 한계 (반드시 인지) ──────────────────────────────")
    L.append("  · '밴드에 낙찰자가 있다' ≠ '거기 넣으면 내가 낙찰'.")
    L.append("    경쟁자도 거기 몰리며, 실제 낙찰은 그날 추첨+동점처리에 달림.")
    L.append("    이 도구는 '어디서 승부가 나는지'까지만 검증한다.")
    L.append("  · 본 측정은 글로벌+공종 단위. fallback 레벨별(client/region) 효용은 별도(④).")
    L.append("=" * 60)
    return "\n".join(L)


def main():
    parser = argparse.ArgumentParser(description="분포 엔진 백테스트 (①②③)")
    parser.add_argument("--cutoff", default="2025-01-01", help="학습/검증 분리일 (기본 2025-01-01)")
    parser.add_argument("--clip", type=float, default=5.0, help="offset 이상치 제거 한계 %% (기본 5)")
    parser.add_argument("--min-bin", type=int, default=200, help="캘리브레이션 bin 최소 표본 (기본 200)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"DB 없음: {DB_PATH}")
        sys.exit(1)

    con = sqlite3.connect(str(DB_PATH))
    try:
        train, test = load_rows(con, args.cutoff, args.clip)
        ptypes = primary_types(con)
        train_p, test_p = load_projects(con, args.cutoff, args.clip)
    finally:
        con.close()

    if not train or not test:
        print(f"데이터 부족 — train={len(train)} test={len(test)}")
        sys.exit(1)

    stab = section_stability(train, test, ptypes)
    calib = section_calibration(train, test, args.min_bin)
    band = section_band(stab, test)
    fb = section_fallback(train_p, test_p)

    report = build_report(args.cutoff, stab, calib, band) + "\n" + build_fallback_report(fb)
    print(report)

    today = datetime.now().strftime("%Y%m%d")
    out = DB_PATH.parent / f"backtest_dist_{today}.md"
    out.write_text("```\n" + report + "\n```\n", encoding="utf-8")
    print(f"\n리포트 저장: {out}")


if __name__ == "__main__":
    main()
