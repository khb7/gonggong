/**
 * 과거 실제 사정률 분포 위에 사용자가 고른 사정률 c 를 긋는다 (T-038).
 *
 * 투찰가가 유효한 조건은 하나다: **c ≥ 실제 사정률**. A값이 있어도 같다
 * (`app/api/v1/bidding.py` 상단 증명). 그래서 "이 c 를 넣으면 어떻게 되나" 는
 * 예측이 아니라 과거 분포에서 c 왼쪽(유효)과 오른쪽(무효)의 비율이다.
 *
 * 근접률은 c 바로 아래 0.10%p 안에 실제 사정률이 있었던 비율이다. 유효하면서
 * 낙찰선에 붙어 있던 경우로, c 를 올리면 유효율은 오르지만 이건 내려간다.
 * 그 trade-off 가 이 화면이 보여주려는 전부다.
 *
 * 백엔드는 bin 별 개수만 보내고 (폭 0.05%p), 여기서 c 를 움직일 때마다 계산한다.
 * c 가 bin 안에 걸치면 bin 안에서 균등하다고 보고 비례로 나눈다.
 */
import type { PrepriceHistogram } from "@/lib/api";

/** 근접 판정 폭 (소수). 0.10%p = bin 두 개. */
export const NEAR_WIDTH = 0.001;

export interface PrepriceOutcome {
  /** 실제 사정률 ≤ c 였던 공고 비율 (0~1). 표본 없으면 null */
  valid: number | null;
  /** 실제 사정률이 (c − 0.10%p, c] 였던 비율 (0~1). 표본 없으면 null */
  near: number | null;
}

export interface PrepriceChartRow {
  /** bin 하한 (%) — x축 라벨 */
  rate_pct: number;
  valid: number;
  invalid: number;
}

/** 값이 x 이하인 공고 수 (bin 안 균등 가정). */
function countBelow(h: PrepriceHistogram, x: number): number {
  let total = 0;
  for (let i = 0; i < h.counts.length; i++) {
    const lo = h.bin_start + h.bin_width * i;
    const hi = lo + h.bin_width;
    if (x >= hi) total += h.counts[i];
    else if (x > lo) total += h.counts[i] * ((x - lo) / h.bin_width);
    else break;
  }
  return total;
}

export function prepriceOutcome(h: PrepriceHistogram, c: number): PrepriceOutcome {
  if (h.n <= 0) return { valid: null, near: null };
  const below = countBelow(h, c);
  const belowNear = countBelow(h, c - NEAR_WIDTH);
  return { valid: below / h.n, near: (below - belowNear) / h.n };
}

export function prepriceChartData(h: PrepriceHistogram, c: number): PrepriceChartRow[] {
  const rows: PrepriceChartRow[] = [];
  for (let i = 0; i < h.counts.length; i++) {
    const n = h.counts[i];
    const lo = h.bin_start + h.bin_width * i;
    const hi = lo + h.bin_width;
    let valid: number;
    if (c >= hi) valid = n;
    else if (c <= lo) valid = 0;
    else valid = n * ((c - lo) / h.bin_width);
    rows.push({
      rate_pct: Math.round(lo * 100000) / 1000,
      valid,
      invalid: n - valid,
    });
  }
  // 양끝의 빈 bin 은 잘라낸다 — 97~103% 를 다 그리면 가운데가 눌린다
  let first = 0;
  while (first < rows.length && h.counts[first] === 0) first++;
  let last = rows.length - 1;
  while (last >= first && h.counts[last] === 0) last--;
  return rows.slice(first, last + 1);
}
