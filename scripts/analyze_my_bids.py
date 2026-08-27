"""
자사 투찰 기록 진단 — Info21c `나의 투찰 성향` 엑셀 분석.

Info21c 웹(`/mybox/myres`) → 엑셀 저장으로 받은 파일을 읽어,
자사 사정률 추정이 실제로 정보를 담고 있는지 검정한다.

핵심 질문: **예측을 하는 것이 안 하는 것보다 나은가?**

  자사 추정오차 sd  <  실제 사정률 자체의 sd   →  예측에 가치 있음
  자사 추정오차 sd  >  실제 사정률 자체의 sd   →  노이즈만 얹고 있음 (예측 끄는 게 낫다)

사용법:
  python scripts/analyze_my_bids.py
  python scripts/analyze_my_bids.py --glob "data/downloads/인포나의투찰성향*.xlsx"

파일을 여러 개 받아 두면 전부 합쳐서 `입찰공고번호` 기준으로 중복을 제거한다
(페이지별로 나눠 받은 경우를 위한 것).

엑셀 레이아웃: 1행이 리포트 제목, 2행이 헤더 → `header=1`.
기대 컬럼: 입찰공고번호, 발주처, 개찰일, 예비기초금액, A값, 예정가격,
          발주처사정율, (자사) 사정율, 사정율편차, (자사) 입찰금액,
          1순위금액, 낙찰하한가, 낙찰하한금액차, 자사순위
"""

import argparse
import glob as globlib
import io
import statistics as st
import sys
from pathlib import Path

import pandas as pd

# Windows 콘솔 UTF-8 (다른 스크립트와 동일 처리)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DEFAULT_GLOB = "data/downloads/인포나의투찰성향*.xlsx"

# DB 전체(12,010건)에서 측정한 사정률 산포. 표본이 작을 때 비교 기준으로 쓴다.
DB_PREPRICE_SD_PCT = 0.729

# 필수 컬럼 — 하나라도 없으면 레이아웃이 바뀐 것이므로 즉시 실패시킨다.
REQUIRED = [
    "입찰공고번호", "발주처", "발주처사정율", "(자사) 사정율",
    "낙찰하한가", "1순위금액", "낙찰하한금액차", "자사순위",
]


def _num(series: pd.Series) -> pd.Series:
    """'100.3656 (0.3656)' / '1,684,976,409' 같은 셀에서 앞쪽 숫자만 뽑는다."""
    return pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.extract(r"(-?[\d.]+)")[0],
        errors="coerce",
    )


def load(pattern: str) -> pd.DataFrame:
    paths = sorted(Path(p) for p in globlib.glob(pattern))
    if not paths:
        raise SystemExit(f"파일을 찾지 못했습니다: {pattern}")

    frames = []
    for p in paths:
        df = pd.read_excel(p, header=1)
        df.columns = [str(c).strip() for c in df.columns]
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            raise SystemExit(f"{p.name}: 필수 컬럼 누락 {missing}\n실제 컬럼: {df.columns.tolist()}")
        print(f"  읽음: {p.name}  ({len(df)}행)")
        frames.append(df)

    d = pd.concat(frames, ignore_index=True)
    before = len(d)
    d = d.drop_duplicates(subset=["입찰공고번호"], keep="first").reset_index(drop=True)
    if before != len(d):
        print(f"  중복 제거: {before} → {len(d)}행")
    return d


def prepare(d: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        "공고번호":   d["입찰공고번호"].astype(str).str.strip(),
        "발주처":     d["발주처"].astype(str).str.strip(),
        "실제사정율": _num(d["발주처사정율"]),
        "자사사정율": _num(d["(자사) 사정율"]),
        "하한가":     _num(d["낙찰하한가"]),
        "하한차":     _num(d["낙찰하한금액차"]),
        "일순위금액": _num(d["1순위금액"]),
        "순위":       _num(d["자사순위"]),
    })
    if "개찰일" in d.columns:
        out["개찰일"] = d["개찰일"].astype(str).str.strip()

    # 오차는 파일의 '사정율편차' 를 그대로 쓰지 않고 다시 계산한다 —
    # 편차 컬럼이 없는 구버전 파일도 있고, 부호 규약을 우리가 고정하는 편이 안전하다.
    # 양수 = 내가 실제보다 낮게 봤다.
    out["오차"] = out["실제사정율"] - out["자사사정율"]
    out["하한대비%"] = out["하한차"] / out["하한가"] * 100
    out["낙찰자하한대비%"] = (out["일순위금액"] - out["하한가"]) / out["하한가"] * 100

    return out.dropna(subset=["실제사정율", "자사사정율", "하한가"]).reset_index(drop=True)


def report(d: pd.DataFrame) -> None:
    n = len(d)
    print(f"\n{'='*70}\n표본 {n}건", end="")
    if "개찰일" in d.columns:
        print(f"   ({d['개찰일'].min()} ~ {d['개찰일'].max()})", end="")
    print(f"\n{'='*70}")

    sd_err = st.stdev(d["오차"]) if n > 1 else float("nan")
    sd_mkt = st.stdev(d["실제사정율"]) if n > 1 else float("nan")

    print("\n① 예측이 무예측보다 나은가")
    print(f"   자사 추정오차 sd        {sd_err:>7.3f} %p")
    print(f"   실제 사정률 자체의 sd    {sd_mkt:>7.3f} %p   ← 예측 없이 평균만 써도 이만큼은 맞는다")
    print(f"   (참고) DB 12,010건 sd    {DB_PREPRICE_SD_PCT:>7.3f} %p")
    ratio = sd_err / sd_mkt if sd_mkt else float("nan")
    verdict = "예측이 노이즈만 얹고 있다 — 끄는 게 낫다" if ratio > 1 else "예측에 가치가 있다"
    print(f"   → 비율 {ratio:.2f}배.  {verdict}")

    print(f"\n   편향 점검: 오차 평균 {d['오차'].mean():+.4f} %p "
          f"(0 에 가까우면 방향이 아니라 폭이 문제)")

    try:
        from scipy.stats import pearsonr
        r, p = pearsonr(d["자사사정율"], d["실제사정율"])
        print(f"   예측력: 자사 vs 실제 상관 r = {r:+.3f}  (p={p:.3f}, n={n})")
    except ImportError:
        print("   예측력: scipy 없음 — 상관 생략")

    print("\n② 무효율 (하한 미달 = 실격)")
    inval = int((d["하한차"] < 0).sum())
    print(f"   현재: {inval}/{n} ({inval/n*100:.0f}%)")
    for label, fixed in (("100.00 고정", 100.0), (f"표본 평균 {d['실제사정율'].mean():.2f} 고정", d["실제사정율"].mean())):
        off = d["실제사정율"] - fixed          # 하한대비% ≈ 실제 − 내가 건 값
        print(f"   반사실 [{label:>20s}]: {int((off<0).sum())}/{n} ({(off<0).mean()*100:.0f}%)"
              f"   |오차|<0.05%p {int((off.abs()<0.05).sum())}건   sd {st.stdev(off):.3f}%p")
    print(f"   {'현재 방식':>28s} :  {inval}/{n}"
          f"   |오차|<0.05%p {int((d['오차'].abs()<0.05).sum())}건   sd {sd_err:.3f}%p")

    print("\n③ 표적의 폭 — 낙찰자는 하한가 위 어디에 있나")
    g = d["낙찰자하한대비%"].dropna()
    if len(g):
        print(f"   중앙 {g.median():+.5f}%   최대 {g.max():+.5f}%   최소 {g.min():+.5f}%")

    print("\n④ 자사 위치")
    q = d["하한대비%"].dropna()
    if len(q):
        print("   하한대비%: " + "  ".join(f"p{p}={q.quantile(p/100):+.3f}" for p in (5, 25, 50, 75, 95)))
    valid = d[d["하한차"] >= 0]
    if len(valid):
        print(f"   유효 {len(valid)}건의 순위: 최고 {int(valid['순위'].min())}위   중앙 {int(valid['순위'].median())}위")

    if d["발주처"].nunique() > 1:
        print("\n⑤ 발주처별 (3건 이상)")
        g = d.groupby("발주처")
        rows = []
        for name, s in g:
            if len(s) < 3:
                continue
            rows.append((name, len(s), s["실제사정율"].mean(), st.stdev(s["실제사정율"]) if len(s) > 1 else 0,
                         st.stdev(s["오차"]) if len(s) > 1 else 0, (s["하한차"] < 0).mean() * 100))
        if rows:
            print(f"   {'발주처':24s} {'n':>4} {'실제평균':>9} {'실제sd':>8} {'오차sd':>8} {'무효율':>7}")
            for name, k, m, sm, se, iv in sorted(rows, key=lambda r: -r[1]):
                print(f"   {name[:23]:24s} {k:>4} {m:>9.4f} {sm:>8.3f} {se:>8.3f} {iv:>6.0f}%")
        else:
            print("   (3건 이상인 발주처 없음)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default=DEFAULT_GLOB, help=f"엑셀 경로 패턴 (기본: {DEFAULT_GLOB})")
    args = ap.parse_args()

    print(f"1. 파일 로드: {args.glob}")
    d = prepare(load(args.glob))
    report(d)


if __name__ == "__main__":
    main()
