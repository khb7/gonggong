import { describe, it, expect } from "vitest";
import { prepriceOutcome, prepriceChartData, NEAR_WIDTH } from "@/lib/preprice";
import type { PrepriceHistogram } from "@/lib/api";

// bin 폭 0.05%p, 97%~103%. counts 에 (사정률 → 개수) 를 찍어 넣는다.
function hist(entries: Record<string, number>, law: PrepriceHistogram["law"] = "local"): PrepriceHistogram {
  const counts = new Array(120).fill(0);
  let n = 0;
  for (const [rate, c] of Object.entries(entries)) {
    const i = Math.round((Number(rate) - 0.97) / 0.0005);
    counts[i] += c;
    n += c;
  }
  return { law, n, bin_start: 0.97, bin_width: 0.0005, counts };
}

describe("prepriceOutcome", () => {
  it("유효율 = 실제 사정률이 c 이하인 공고 비율", () => {
    // 0.9990 bin(0.9990~0.9995) 2건, 1.0010 bin 1건, 1.0025 bin 1건
    const h = hist({ "0.9990": 2, "1.0010": 1, "1.0025": 1 });
    // c=1.0020 은 1.0020 bin 하한 — 아래 3건이 유효
    expect(prepriceOutcome(h, 1.002).valid).toBeCloseTo(0.75);
    // c=1.0030 이면 전부 유효
    expect(prepriceOutcome(h, 1.003).valid).toBeCloseTo(1);
    // c=0.9990 이면 아무것도 유효하지 않다
    expect(prepriceOutcome(h, 0.999).valid).toBeCloseTo(0);
  });

  it("c 가 bin 안에 걸치면 bin 안에서 균등하다고 보고 나눈다", () => {
    const h = hist({ "1.0000": 10 });          // 1.0000~1.0005 에 10건
    expect(prepriceOutcome(h, 1.00025).valid).toBeCloseTo(0.5);
    expect(prepriceOutcome(h, 1.0001).valid).toBeCloseTo(0.2);
  });

  it("근접률 = c 바로 아래 0.10%p 안에 있는 비율 — 낙찰선에 붙은 공고", () => {
    expect(NEAR_WIDTH).toBe(0.001);
    // 1.0005 bin, 1.0010 bin 각 1건 = (1.0005, 1.0015] 구간, 그 아래 0.9990 에 2건
    const h = hist({ "0.9990": 2, "1.0005": 1, "1.0010": 1 });
    const o = prepriceOutcome(h, 1.0015);
    expect(o.valid).toBeCloseTo(1);
    expect(o.near).toBeCloseTo(0.5);
  });

  it("c 를 올리면 유효율은 오르고 근접률은 내려간다 — 그 trade-off 를 보여주는 게 목적이다", () => {
    const h = hist({ "0.9990": 3, "1.0000": 3, "1.0010": 3, "1.0020": 3 });
    const lo = prepriceOutcome(h, 1.001);
    const hi = prepriceOutcome(h, 1.004);
    expect(hi.valid).toBeGreaterThan(lo.valid);
    expect(hi.near).toBeLessThan(lo.near);
  });

  it("표본이 없으면 null 이다 — 0% 로 찍으면 거짓말이다", () => {
    const h = hist({});
    expect(prepriceOutcome(h, 1.0015)).toEqual({ valid: null, near: null });
  });
});

describe("prepriceChartData", () => {
  it("bin 마다 유효/무효로 나누고, 양끝의 빈 bin 은 잘라낸다", () => {
    const h = hist({ "0.9990": 2, "1.0010": 1 });
    const rows = prepriceChartData(h, 1.0);
    // 0.9990 ~ 1.0010 사이 bin 만 남는다 (5개)
    expect(rows.length).toBe(5);
    expect(rows[0]).toMatchObject({ rate_pct: 99.9, valid: 2, invalid: 0 });
    expect(rows[4]).toMatchObject({ rate_pct: 100.1, valid: 0, invalid: 1 });
  });

  it("c 가 걸친 bin 은 균등 가정으로 쪼갠다", () => {
    const h = hist({ "1.0000": 10 });
    const rows = prepriceChartData(h, 1.00025);
    expect(rows).toHaveLength(1);
    expect(rows[0].valid).toBeCloseTo(5);
    expect(rows[0].invalid).toBeCloseTo(5);
  });

  it("표본이 없으면 빈 배열", () => {
    expect(prepriceChartData(hist({}), 1.0015)).toEqual([]);
  });
});
