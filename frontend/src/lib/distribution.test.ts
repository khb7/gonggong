import { describe, it, expect } from "vitest";
import {
  prepareDistribution,
  computeLocalPosition,
  computeMyOffsetPct,
} from "@/lib/distribution";
import type { OffsetBucket } from "@/lib/api";

// ── 헬퍼 ────────────────────────────────────────────────────────────────

function bin(offset_pct: number, count: number, win_count = 0): OffsetBucket {
  return {
    offset_pct,
    count,
    win_count,
    historical_win_rate: count > 0 ? (win_count / count) * 100 : null,
  };
}

// ── prepareDistribution ─────────────────────────────────────────────────

describe("prepareDistribution", () => {
  it("빈 배열이면 빈 결과를 반환한다", () => {
    const r = prepareDistribution([]);
    expect(r.bins).toEqual([]);
    expect(r.totalCount).toBe(0);
  });

  it("count 합이 0이면 빈 결과를 반환한다", () => {
    expect(prepareDistribution([bin(-0.5, 0), bin(-0.4, 0)]).bins).toEqual([]);
  });

  it("bin 하나면 그대로 반환한다", () => {
    const r = prepareDistribution([bin(-0.6, 10)]);
    expect(r.bins).toHaveLength(1);
    expect(r.bins[0].offset_pct).toBe(-0.6);
  });

  it("중간 gap 을 count:0 으로 채운다", () => {
    // -0.4 가 비어 있다 (tailRatio 0 → 클램프 없음)
    const r = prepareDistribution([bin(-0.6, 10), bin(-0.5, 10), bin(-0.3, 10)], 0);
    expect(r.bins.map((b) => b.offset_pct)).toEqual([-0.6, -0.5, -0.4, -0.3]);
    expect(r.bins[2].count).toBe(0);
    expect(r.bins[2].win_count).toBe(0);
  });

  it("연속된 여러 gap 을 모두 채운다", () => {
    const r = prepareDistribution([bin(-1.0, 5), bin(-0.5, 5)], 0);
    expect(r.bins).toHaveLength(6); // -1.0 ~ -0.5
    expect(r.bins.filter((b) => b.count === 0)).toHaveLength(4);
  });

  it("채워진 bin 의 historical_win_rate 는 0 이 아니라 null 이다", () => {
    const r = prepareDistribution([bin(-0.6, 10), bin(-0.4, 10)], 0);
    const filled = r.bins.find((b) => b.offset_pct === -0.5)!;
    expect(filled.historical_win_rate).toBeNull();
  });

  it("기존 bin 의 win_count 를 보존한다", () => {
    const r = prepareDistribution([bin(-0.8, 20, 7), bin(-0.6, 10, 2)], 0);
    expect(r.bins.find((b) => b.offset_pct === -0.8)!.win_count).toBe(7);
    expect(r.bins.find((b) => b.offset_pct === -0.6)!.win_count).toBe(2);
  });

  it("음수·양수 경계를 건너뛰지 않는다", () => {
    const r = prepareDistribution([bin(-0.2, 5), bin(0.2, 5)], 0);
    expect(r.bins.map((b) => b.offset_pct)).toEqual([-0.2, -0.1, 0, 0.1, 0.2]);
  });

  it("부동소수점 오차가 있어도 bin 개수가 정확하다", () => {
    // 0.1 씩 누적하면 0.30000000000000004 같은 값이 생긴다
    const r = prepareDistribution([bin(-3.1, 100), bin(2.1, 100)], 0);
    expect(r.bins).toHaveLength(53); // -3.1 ~ 2.1
    expect(r.bins[r.bins.length - 1].offset_pct).toBeCloseTo(2.1, 10);
  });

  it("입력이 정렬돼 있지 않아도 동작한다", () => {
    const r = prepareDistribution([bin(0.2, 5), bin(-0.2, 5), bin(0.0, 5)], 0);
    expect(r.bins.map((b) => b.offset_pct)).toEqual([-0.2, -0.1, 0, 0.1, 0.2]);
  });

  it("꼬리 아웃라이어를 클램프하고 제외 건수를 보고한다", () => {
    // 실제 데이터 형태: 코어에 대량, 극단에 오염 행 소수
    const core = Array.from({ length: 53 }, (_, i) => bin(-3.1 + i / 10, 1000));
    const dist = [bin(-463, 1), ...core, bin(7941, 1)];

    const r = prepareDistribution(dist);
    expect(r.rangeFrom).toBeGreaterThanOrEqual(-10);
    expect(r.rangeTo).toBeLessThanOrEqual(10);
    expect(r.excludedCount).toBe(2);
    expect(r.bins.every((b) => b.offset_pct >= -10 && b.offset_pct <= 10)).toBe(true);
  });

  it("표본이 적어 분위수가 무력해도 하드 상·하한이 범위를 막는다", () => {
    // N=2 → tailRatio 0.5% 가 1건에도 못 미쳐 분위수가 전 범위를 남긴다
    const r = prepareDistribution([bin(-500, 1), bin(0, 1)]);
    expect(r.rangeFrom).toBe(-10);
    expect(r.excludedCount).toBe(1);
  });

  it("제외된 낙찰 건수를 따로 보고한다", () => {
    const core = Array.from({ length: 21 }, (_, i) => bin(-1 + i / 10, 1000, 1));
    const r = prepareDistribution([bin(-50, 1, 1), ...core]);
    expect(r.excludedWinCount).toBe(1);
  });

  it("클램프할 게 없으면 아무것도 제외하지 않는다", () => {
    const core = Array.from({ length: 21 }, (_, i) => bin(-1 + i / 10, 100, 1));
    const r = prepareDistribution(core);
    expect(r.excludedCount).toBe(0);
    expect(r.excludedWinCount).toBe(0);
    expect(r.bins).toHaveLength(21);
  });
});

// ── computeLocalPosition ────────────────────────────────────────────────

describe("computeLocalPosition", () => {
  const { bins } = prepareDistribution(
    [bin(-0.8, 20, 5), bin(-0.7, 30, 3), bin(-0.5, 50, 2)],
    0,
  );
  // bins: -0.8(20) -0.7(30) -0.6(0, 채워짐) -0.5(50)

  const basePrice = 100_000_000;
  const llr = 0.87745;
  const priceAt = (offsetPct: number) => Math.round(basePrice * (llr + offsetPct / 100));

  it("bins 가 비면 null", () => {
    expect(computeLocalPosition(priceAt(-0.7), basePrice, llr, [])).toBeNull();
  });

  it("투찰가나 기초금액이 0 이하면 null", () => {
    expect(computeLocalPosition(0, basePrice, llr, bins)).toBeNull();
    expect(computeLocalPosition(priceAt(-0.7), 0, llr, bins)).toBeNull();
  });

  it("표시 범위 밖이면 null", () => {
    expect(computeLocalPosition(priceAt(-5.0), basePrice, llr, bins)).toBeNull();
  });

  it("정상 구간의 offset·표본수·낙찰빈도를 반환한다", () => {
    const pos = computeLocalPosition(priceAt(-0.7), basePrice, llr, bins)!;
    expect(pos.offset_pct).toBeCloseTo(-0.7, 10);
    expect(pos.sample_count).toBe(30);
    expect(pos.historical_win_rate).toBeCloseTo(10, 5);
  });

  it("참여 0건 구간도 null 이 아니라 위치를 반환한다", () => {
    // 채워진 bin(-0.6) — 범위 밖이 아니므로 "범위 밖" 처리하면 안 된다
    const pos = computeLocalPosition(priceAt(-0.6), basePrice, llr, bins)!;
    expect(pos).not.toBeNull();
    expect(pos.sample_count).toBe(0);
    expect(pos.historical_win_rate).toBeNull();
  });

  it("percentile 은 내 구간보다 낮은 참여 비율이다", () => {
    // -0.5 기준 아래: 20 + 30 + 0 = 50 / 전체 100 = 50%
    const pos = computeLocalPosition(priceAt(-0.5), basePrice, llr, bins)!;
    expect(pos.percentile).toBeCloseTo(50, 5);
  });

  it("채워진 bin 은 percentile 합계를 바꾸지 않는다", () => {
    const raw = [bin(-0.8, 20, 5), bin(-0.7, 30, 3), bin(-0.5, 50, 2)];
    const withGaps = prepareDistribution(raw, 0).bins;
    const posFilled = computeLocalPosition(priceAt(-0.5), basePrice, llr, withGaps)!;
    const posRaw = computeLocalPosition(priceAt(-0.5), basePrice, llr, raw)!;
    expect(posFilled.percentile).toBeCloseTo(posRaw.percentile, 10);
  });

  it("estimated_price 는 기초금액 × (하한율 + offset)", () => {
    const pos = computeLocalPosition(priceAt(-0.7), basePrice, llr, bins)!;
    expect(pos.estimated_price).toBe(priceAt(-0.7));
  });
});

// ── describeScope / winRateIsBroader ────────────────────────────────────

import { describeScope, winRateIsBroader, DEFAULT_QUALITY } from "@/lib/distribution";
import type { DistributionQuality } from "@/lib/api";

const q = (over: Partial<DistributionQuality> = {}): DistributionQuality => ({
  ...DEFAULT_QUALITY,
  ...over,
});

describe("describeScope", () => {
  it("발주처 레벨이면 발주처명을 배지에 쓴다", () => {
    const s = describeScope(
      q({ distribution_level: "client", distribution_label: "서울주택도시공사", sample_notices: 40 }),
    );
    expect(s.text).toBe("서울주택도시공사 기준");
    expect(s.tone).toBe("specific");
    expect(s.hint).toContain("40건");
  });

  it("지역으로 폴백하면 넓혔다는 사실을 알린다", () => {
    const s = describeScope(
      q({ distribution_level: "region", distribution_label: "서울", sample_notices: 78 }),
    );
    expect(s.text).toBe("서울 지역 기준");
    expect(s.tone).toBe("broad");
    expect(s.hint).toContain("발주처 표본이 부족");
  });

  it("공종 레벨이면 공종명을 쓴다", () => {
    const s = describeScope(
      q({ distribution_level: "type_bucket", distribution_label: "실내건축", sample_notices: 120 }),
    );
    expect(s.text).toBe("실내건축 공종 기준");
    expect(s.tone).toBe("broad");
  });

  it("global이면 전체 기준으로 표시한다", () => {
    const s = describeScope(q({ distribution_level: "global", sample_notices: 362 }));
    expect(s.text).toBe("전체 기준");
    expect(s.hint).toContain("362건");
  });
});

describe("winRateIsBroader", () => {
  it("막대와 낙찰률 표본이 다르면 true", () => {
    expect(winRateIsBroader(q({ distribution_level: "client", win_rate_level: "global" }))).toBe(true);
  });

  it("둘 다 global이면 false", () => {
    expect(winRateIsBroader(q({ distribution_level: "global", win_rate_level: "global" }))).toBe(false);
  });
});

// ── findWinZone / zoneWinRate ───────────────────────────────────────────

import { findWinZone, zoneWinRate } from "@/lib/distribution";

describe("findWinZone", () => {
  it("빈 배열이면 null", () => {
    expect(findWinZone([])).toBeNull();
  });

  it("낙찰이 하나도 없으면 null", () => {
    expect(findWinZone([bin(-0.5, 100), bin(-0.4, 100)])).toBeNull();
  });

  it("낙찰이 몰린 최소 구간을 찾는다", () => {
    // 낙찰 20건 중 12건이 -0.7 ~ -0.6 에 몰려 있다
    const bins = [
      bin(-0.9, 100, 1), bin(-0.8, 100, 1),
      bin(-0.7, 100, 6), bin(-0.6, 100, 6),
      bin(-0.5, 100, 1), bin(-0.4, 100, 5),
    ];
    const z = findWinZone(bins, 0.6)!;
    expect(z.from).toBeCloseTo(-0.7, 10);
    expect(z.to).toBeCloseTo(-0.6, 10);
    expect(z.wins).toBe(12);
    expect(z.totalWins).toBe(20);
    expect(z.ratio).toBeCloseTo(60, 5);
    expect(z.binCount).toBe(2);
  });

  it("더 넓은 구간보다 좁은 구간을 고른다", () => {
    const bins = [
      bin(-0.9, 10, 3), bin(-0.8, 10, 0), bin(-0.7, 10, 3),
      bin(-0.6, 10, 6),
    ];
    // 0.5 -> 6건 필요. [-0.6] 단독(6건)이 [-0.9~-0.7](6건)보다 좁다
    const z = findWinZone(bins, 0.5)!;
    expect(z.binCount).toBeLessThanOrEqual(3);
    expect(z.wins).toBeGreaterThanOrEqual(6);
  });

  it("단일 bin 에 몰리면 좌우로 한 칸씩 넓힌다", () => {
    const bins = [bin(-0.7, 10, 0), bin(-0.6, 10, 10), bin(-0.5, 10, 0)];
    const z = findWinZone(bins, 0.6)!;
    expect(z.binCount).toBe(3);
    expect(z.from).toBeCloseTo(-0.7, 10);
    expect(z.to).toBeCloseTo(-0.5, 10);
  });

  it("구간이 전체 폭의 대부분을 덮으면 null (집중 구간 없음)", () => {
    // 낙찰이 균등하게 흩어져 있으면 60% 를 담는 데 폭 대부분이 필요하다
    const bins = Array.from({ length: 10 }, (_, i) => bin(-1 + i / 10, 100, 5));
    expect(findWinZone(bins, 0.6)).toBeNull();
  });

  it("widthRatio 는 전체 대비 구간 폭 비율이다", () => {
    const bins = Array.from({ length: 20 }, (_, i) =>
      bin(-1 + i / 10, 100, i >= 5 && i < 8 ? 10 : 0),
    );
    const z = findWinZone(bins, 0.6)!;
    expect(z.totalBins).toBe(20);
    expect(z.widthRatio).toBeCloseTo((z.binCount / 20) * 100, 5);
  });

  it("targetRatio 가 범위를 벗어나면 기본값으로 되돌린다", () => {
    const bins = [bin(-0.7, 10, 1), bin(-0.6, 10, 9), bin(-0.5, 10, 0)];
    expect(findWinZone(bins, 0)).toEqual(findWinZone(bins));
    expect(findWinZone(bins, 2)).toEqual(findWinZone(bins));
  });

  it("count 가 0 인 채워진 bin 이 섞여도 동작한다", () => {
    const { bins } = prepareDistribution(
      [bin(-0.8, 100, 6), bin(-0.7, 100, 6), bin(-0.4, 100, 8)],
      0,
    );
    const z = findWinZone(bins, 0.6)!;
    expect(z.wins).toBeGreaterThanOrEqual(12);
  });
});

describe("zoneWinRate", () => {
  const bins = [
    bin(-0.9, 1000, 1), bin(-0.8, 1000, 10), bin(-0.7, 1000, 9),
    bin(-0.6, 1000, 1), bin(-0.5, 1000, 1),
  ];

  it("구간 안팎의 낙찰률과 배수를 계산한다", () => {
    const z = findWinZone(bins, 0.6)!;
    const r = zoneWinRate(bins, z)!;
    // 구간 -0.8 ~ -0.7: 19건 / 2000명 = 0.95%
    // 구간 밖:          3건 / 3000명 = 0.10%
    expect(r.inZoneRate).toBeCloseTo(0.95, 5);
    expect(r.outZoneRate).toBeCloseTo(0.1, 5);
    expect(r.multiple).toBeCloseTo(9.5, 5);
  });

  it("구간 밖 낙찰이 0 이면 배수를 낼 수 없어 null", () => {
    const only = [bin(-0.7, 100, 0), bin(-0.6, 100, 10), bin(-0.5, 100, 0)];
    const z = findWinZone(only, 0.6)!;
    expect(zoneWinRate(only, z)).toBeNull();
  });

  it("구간이 전체를 덮어 바깥 참여자가 없으면 null", () => {
    const two = [bin(-0.6, 100, 5), bin(-0.5, 100, 5)];
    const z = findWinZone(two, 0.6);
    if (z) expect(zoneWinRate(two, z)).toBeNull();
  });
});

// ── computeLocalPosition + A값 ──────────────────────────────────────────

describe("computeLocalPosition — A값", () => {
  const { bins } = prepareDistribution(
    [bin(-0.8, 20, 5), bin(-0.7, 30, 3), bin(-0.5, 50, 2)],
    0,
  );

  const basePrice = 100_000_000;
  const llr = 0.87745;

  /**
   * A값이 반영된 실제 투찰금액.
   * 분포 축은 조정 투찰율 기준이므로 (예정가격 − A) × rate + A 로 되돌린다.
   */
  const priceAt = (offsetPct: number, a: number) =>
    Math.round((basePrice - a) * (llr + offsetPct / 100) + a);

  it("A값이 0이면 기존 계산과 같다", () => {
    const withZero = computeLocalPosition(priceAt(-0.7, 0), basePrice, llr, bins, 0)!;
    const omitted = computeLocalPosition(priceAt(-0.7, 0), basePrice, llr, bins)!;
    expect(withZero).toEqual(omitted);
  });

  it("A값을 넘기면 조정 투찰율 기준 offset 이 나온다", () => {
    const a = 5_000_000;
    const pos = computeLocalPosition(priceAt(-0.7, a), basePrice, llr, bins, a)!;
    expect(pos.offset_pct).toBeCloseTo(-0.7, 10);
  });

  it("A값 공고인데 A값을 빼먹으면 위치가 오른쪽으로 밀린다", () => {
    // 밀린 위치까지 담으려면 축이 넓어야 한다
    const wide = prepareDistribution(
      [bin(-2.0, 10, 1), bin(-0.7, 30, 3), bin(2.0, 10, 1)],
      0,
    ).bins;

    const a = 5_000_000;
    const price = priceAt(-0.7, a);

    const correct = computeLocalPosition(price, basePrice, llr, wide, a)!;
    const forgotten = computeLocalPosition(price, basePrice, llr, wide, 0)!;

    expect(correct.offset_pct).toBeCloseTo(-0.7, 10);
    // A값 5% → (1−하한율) × A/(기초금액−A) ≈ +0.64%p 만큼 오른쪽으로 밀린다
    expect(forgotten.offset_pct).toBeGreaterThan(correct.offset_pct);
    expect(forgotten.offset_pct - correct.offset_pct).toBeCloseTo(0.6, 1);
  });

  it("estimated_price 는 입력 투찰가를 되돌려준다", () => {
    const a = 5_000_000;
    const price = priceAt(-0.7, a);
    const pos = computeLocalPosition(price, basePrice, llr, bins, a)!;
    expect(pos.estimated_price).toBeCloseTo(price, -1);
  });

  it("A값이 기초금액 이상이면 이상값으로 보고 무시한다", () => {
    const price = priceAt(-0.7, 0);
    const pos = computeLocalPosition(price, basePrice, llr, bins, basePrice * 2)!;
    expect(pos.offset_pct).toBeCloseTo(-0.7, 10);
  });
});

describe("computeMyOffsetPct — 배지와 카드가 같은 값을 써야 한다", () => {
  const basePrice = 800_000_000;
  const llr = 0.87745;

  it("A값을 반영한다", () => {
    const a = 30_000_000;
    // 낙찰하한가 = (기초금액 − A) × 하한율 + A
    const floor = (basePrice - a) * llr + a;
    expect(computeMyOffsetPct(floor, basePrice, llr, a)).toBeCloseTo(0, 1);
  });

  it("A값을 빼먹으면 오른쪽으로 밀린다 — 실제로 났던 버그", () => {
    const a = 30_000_000;
    const price = 706_000_000;
    const withA = computeMyOffsetPct(price, basePrice, llr, a)!;
    const withoutA = computeMyOffsetPct(price, basePrice, llr, 0)!;

    // 화면에 offset 이 0.0% 와 +0.5% 두 개로 떴던 그 차이다
    expect(withA).toBeCloseTo(0.0, 1);
    expect(withoutA).toBeCloseTo(0.5, 1);
  });

  it("computeLocalPosition 과 값이 일치한다", () => {
    const a = 30_000_000;
    const price = 706_000_000;
    const bins = Array.from({ length: 61 }, (_, i) => ({
      offset_pct: Math.round((i - 30) * 10) / 100,
      count: 10,
      win_count: 1,
      historical_win_rate: 10,
    }));
    const badge = computeMyOffsetPct(price, basePrice, llr, a);
    const card = computeLocalPosition(price, basePrice, llr, bins, a);
    expect(card).not.toBeNull();
    expect(badge).toBe(card!.offset_pct);
  });

  it("투찰가나 기초금액이 없으면 null", () => {
    expect(computeMyOffsetPct(0, basePrice, llr, 0)).toBeNull();
    expect(computeMyOffsetPct(700_000_000, 0, llr, 0)).toBeNull();
  });
});
