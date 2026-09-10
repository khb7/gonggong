import type { DistributionQuality, OffsetBucket } from "@/lib/api";

/**
 * offset 히스토그램 표시용 전처리.
 *
 * 백엔드 build_offset_distribution() 은 관측된 offset 에만 bin 을 만든다.
 * 참여자 0명인 구간은 bin 자체가 없고, recharts 카테고리 축은 없는 bin 을
 * 그냥 접어버리므로 분포 모양이 왜곡된다.
 *
 * 여기서 두 가지를 처리한다.
 *   1. 꼬리 클램프 — 오염 행(bid_rate 이상치)이 범위를 수천 % 로 늘리는 것을 막는다
 *   2. gap 채우기  — 클램프 범위 안의 누락 bin 을 count:0 으로 채워 축을 연속으로 만든다
 */

// ── 상수 ────────────────────────────────────────────────────────────────

/** 양쪽 꼬리에서 잘라낼 비율 (누적 참여 건수 기준) */
const TAIL_RATIO = 0.005;

/** 표시 범위 하드 상·하한 (offset %). 표본이 적어 분위수가 무력할 때의 방어선 */
const HARD_MIN = -10;
const HARD_MAX = 10;

/** offset(%) → 1/10% 단위 정수 키. 부동소수점 오차 회피용 */
const toKey = (pct: number) => Math.round(pct * 10);

// ── 분포 전처리 ─────────────────────────────────────────────────────────

export interface PreparedDistribution {
  /** 클램프 범위 안의 연속 bin 목록 (gap 없음) */
  bins: OffsetBucket[];
  /** 표시 범위 시작 offset (%) */
  rangeFrom: number;
  /** 표시 범위 끝 offset (%) */
  rangeTo: number;
  /** 범위 밖으로 제외된 참여 건수 */
  excludedCount: number;
  /** 범위 밖으로 제외된 낙찰 건수 */
  excludedWinCount: number;
  /** 클램프 전 전체 참여 건수 */
  totalCount: number;
}

const EMPTY: PreparedDistribution = {
  bins: [],
  rangeFrom: 0,
  rangeTo: 0,
  excludedCount: 0,
  excludedWinCount: 0,
  totalCount: 0,
};

export function prepareDistribution(
  dist: OffsetBucket[],
  tailRatio: number = TAIL_RATIO,
): PreparedDistribution {
  if (!dist.length) return EMPTY;

  const sorted = [...dist].sort((a, b) => a.offset_pct - b.offset_pct);
  const totalCount = sorted.reduce((s, b) => s + b.count, 0);
  const totalWins = sorted.reduce((s, b) => s + b.win_count, 0);
  if (totalCount === 0) return EMPTY;

  // ── 1. 누적 분위수로 꼬리 자르기 ──
  let lo = sorted[0].offset_pct;
  let hi = sorted[sorted.length - 1].offset_pct;
  let acc = 0;
  let loFound = false;

  for (const b of sorted) {
    acc += b.count;
    if (!loFound && acc >= totalCount * tailRatio) {
      lo = b.offset_pct;
      loFound = true;
    }
    if (acc >= totalCount * (1 - tailRatio)) {
      hi = b.offset_pct;
      break;
    }
  }

  // ── 2. 하드 상·하한과 교집합 ──
  lo = Math.max(lo, HARD_MIN);
  hi = Math.min(hi, HARD_MAX);
  if (lo > hi) return EMPTY;

  // ── 3. 누락 bin 을 count:0 으로 채우기 ──
  const byKey = new Map(sorted.map((b) => [toKey(b.offset_pct), b]));
  const bins: OffsetBucket[] = [];

  for (let k = toKey(lo); k <= toKey(hi); k++) {
    bins.push(
      byKey.get(k) ?? {
        offset_pct: k / 10,
        count: 0,
        win_count: 0,
        // 참여 0건 구간의 낙찰 빈도는 0% 가 아니라 "값 없음" 이다.
        // 0 으로 채우면 "낙찰 확률 0%" 로 오독된다.
        historical_win_rate: null,
      },
    );
  }

  const keptCount = bins.reduce((s, b) => s + b.count, 0);
  const keptWins = bins.reduce((s, b) => s + b.win_count, 0);

  return {
    bins,
    rangeFrom: lo,
    rangeTo: hi,
    excludedCount: totalCount - keptCount,
    excludedWinCount: totalWins - keptWins,
    totalCount,
  };
}

// ── 내 위치 계산 ────────────────────────────────────────────────────────

export interface LocalPosition {
  offset_pct: number;
  estimated_price: number;
  percentile: number;
  /** 해당 구간 과거 낙찰 빈도 (%). 참여 0건이면 null */
  historical_win_rate: number | null;
  sample_count: number;
  /** 사정률 +1σ 일 때의 offset (%) — 밴드 하단. σ 가 없으면 null */
  offsetLowPct: number | null;
  /** 사정률 −1σ 일 때의 offset (%) — 밴드 상단 */
  offsetHighPct: number | null;
}

/** 사정률을 하나 가정했을 때의 내 offset (%, 0.1% 단위) */
function offsetPctAtRate(
  myBidPrice: number,
  basePrice: number,
  lowerLimitRate: number,
  a: number,
  adjustmentRate: number,
): number {
  const estimatedPrice = basePrice * adjustmentRate;
  const adjusted = (myBidPrice - a) / (estimatedPrice - a);
  return Math.round((adjusted - lowerLimitRate) * 1000) / 10;
}

/**
 * 내 위치의 불확실성 밴드(±1σ)를 계산한다.
 *
 * 히스토그램의 과거 offset 은 개찰로 확정된 **예정가격** 기준이다.
 * 내 투찰가는 개찰 전이라 예정가격을 모르므로 **기초금액**으로 대신 잰다.
 * 자가 서로 달라, 내 화살표는 사정률이 흔들리는 만큼 좌우로 밀린다.
 *
 *     예정가격 = 기초금액 × 사정률
 *     내 offset = (투찰금액 − A) / (기초금액 × 사정률 − A) − 법정하한율
 *
 * 사정률이 크면 분모가 커져 offset 이 작아지므로,
 * 밴드 하단은 (1+σ), 상단은 (1−σ) 에서 나온다.
 *
 * 이 오차는 없앨 수 없다 (예정가격은 개찰 시 정해진다). 폭을 드러내는 게 목적이다.
 * 백엔드 app/engine/distribution.py 의 calc_offset_band() 와 같은 식이다.
 */
export function computeOffsetBand(
  myBidPrice: number,
  basePrice: number,
  lowerLimitRate: number,
  rateSigma: number,
  aValue: number = 0,
): [number, number] | null {
  if (!rateSigma || rateSigma <= 0 || basePrice <= 0 || myBidPrice <= 0) return null;

  const a = aValue > 0 && aValue < basePrice ? aValue : 0;

  // 사정률이 1에서 크게 벗어나 예정가격이 A값 이하로 내려가면 정의되지 않는다.
  if (basePrice * (1 - rateSigma) <= a) return null;

  return [
    offsetPctAtRate(myBidPrice, basePrice, lowerLimitRate, a, 1 + rateSigma),
    offsetPctAtRate(myBidPrice, basePrice, lowerLimitRate, a, 1 - rateSigma),
  ];
}

/**
 * 내 투찰가의 분포상 위치를 계산한다. API 재호출 없이 로컬에서 즉시 계산한다.
 *
 * 분포의 x축은 원본 `투찰율(%)` 기준이고, 그 투찰율은 A값이 제거된 조정값이다.
 *
 *     투찰율 = (투찰금액 − A) / (예정가격 − A)
 *
 * 그래서 내 위치도 같은 방식으로 조정해야 축이 맞는다. A값을 빼지 않으면
 * A값 크기만큼 오른쪽으로 밀린 위치가 나온다.
 * 근거: md/design/bid_rate_definitions.md
 *
 * 사정률≈1.0 근사를 쓴다 (예정가격 ≈ 기초금액).
 * lowerLimitRate 는 **법정** 낙찰하한율이다 (실효 하한율이 아니다).
 *
 * bins 는 prepareDistribution() 의 결과를 넘긴다.
 * 표시 범위 밖이면 null 을 반환한다 (참여 0건인 구간은 null 이 아니다).
 *
 * rateSigma 를 주면 사정률 근사 오차를 ±1σ 밴드로 함께 계산한다
 * (computeOffsetBand 주석 참고). 0 이면 밴드는 null 이다.
 */
/** A값이 예정가격(≈기초금액) 이상이면 이상값 — 0 으로 무시한다. */
function normalizeAValue(aValue: number, basePrice: number): number {
  return aValue > 0 && aValue < basePrice ? aValue : 0;
}

/**
 * 내 투찰가의 offset (%). 분포 x축과 같은 축 위에 놓는다.
 *
 *     offset ≈ (투찰금액 − A) / (기초금액 − A) − 법정하한율
 *
 * **A값을 빼지 않으면 A값 크기만큼 오른쪽으로 밀린다.** 기초금액 8억 / A값 3천만이면
 * +0.5%p 어긋나는데, bin 해상도가 0.1% 라 5칸이나 밀린 자리에 표시된다.
 *
 * 화면 두 곳(입력창 옆 배지, 「내 offset」 카드)이 같은 값을 써야 하므로
 * 여기 한 곳에서만 계산한다. 예전에 배지 쪽이 A값 없이 따로 계산해
 * 같은 화면에 offset 이 두 개(+0.5% vs 0.0%) 뜬 적이 있다.
 *
 * `computeLocalPosition()` 과 달리 표시 범위 밖이어도 값을 돌려준다 —
 * 범위를 벗어났다는 사실 자체를 사용자에게 알려야 하기 때문이다.
 */
export function computeMyOffsetPct(
  myBidPrice: number,
  basePrice: number,
  lowerLimitRate: number,
  aValue: number = 0,
): number | null {
  if (!(myBidPrice > 0) || !(basePrice > 0)) return null;
  const a = normalizeAValue(aValue, basePrice);
  const adjustedRate = (myBidPrice - a) / (basePrice - a);
  return Math.round((adjustedRate - lowerLimitRate) * 1000) / 10;
}

export function computeLocalPosition(
  myBidPrice: number,
  basePrice: number,
  lowerLimitRate: number,
  bins: OffsetBucket[],
  aValue: number = 0,
  rateSigma: number = 0,
): LocalPosition | null {
  if (!bins.length || myBidPrice <= 0 || basePrice <= 0) return null;

  const a = normalizeAValue(aValue, basePrice);
  const myOffsetPct = computeMyOffsetPct(myBidPrice, basePrice, lowerLimitRate, aValue);
  if (myOffsetPct === null) return null;
  const key = toKey(myOffsetPct);

  const matching = bins.find((b) => toKey(b.offset_pct) === key);
  if (!matching) return null;

  const band = computeOffsetBand(myBidPrice, basePrice, lowerLimitRate, rateSigma, aValue);

  const totalCount = bins.reduce((s, b) => s + b.count, 0);
  const lowerCount = bins
    .filter((b) => toKey(b.offset_pct) < key)
    .reduce((s, b) => s + b.count, 0);

  return {
    offset_pct: myOffsetPct,
    // offset → 금액 역변환. A값 조정의 역이므로 (예정가격 − A) × rate + A
    estimated_price: Math.round((basePrice - a) * (lowerLimitRate + myOffsetPct / 100) + a),
    percentile: totalCount > 0 ? Math.round((lowerCount / totalCount) * 1000) / 10 : 0,
    historical_win_rate: matching.count > 0 ? matching.historical_win_rate ?? 0 : null,
    sample_count: matching.count,
    offsetLowPct: band ? band[0] : null,
    offsetHighPct: band ? band[1] : null,
  };
}

// ── 낙찰 집중 구간 ──────────────────────────────────────────────────────

/** 집중 구간이 담아야 할 낙찰 비율 */
const WIN_ZONE_TARGET_RATIO = 0.6;

/**
 * 집중도 최소 기준. 집중도 = 담은 낙찰 비율 ÷ 차지한 폭 비율.
 *
 * 낙찰이 균등하게 흩어져 있으면 60% 를 담는 데 폭도 60% 가 필요해 집중도가 1.0 이다.
 * "폭 대비 몇 배로 몰렸는가" 로 재야 균등분포를 걸러낼 수 있다.
 * (폭 자체에 상한을 두면 균등분포도 통과해버려 기준이 무력해진다)
 */
const WIN_ZONE_MIN_CONCENTRATION = 1.5;

/** 이 미만이면 밴드를 그리되 참고용임을 경고한다 */
export const WIN_ZONE_MIN_SAMPLE = 10;

export interface WinZone {
  /** 구간 시작 offset (%) */
  from: number;
  /** 구간 끝 offset (%) */
  to: number;
  startIndex: number;
  endIndex: number;
  /** 구간 내 낙찰 건수 */
  wins: number;
  /** 전체 낙찰 건수 */
  totalWins: number;
  /** wins / totalWins (%) */
  ratio: number;
  binCount: number;
  totalBins: number;
  /** binCount / totalBins (%) — 얼마나 좁은 구간에 몰렸는지 */
  widthRatio: number;
  /** ratio / widthRatio — 균등분포 대비 몇 배로 몰렸는지 (1.0 이면 균등) */
  concentration: number;
}

/**
 * 전체 낙찰의 targetRatio 를 담는 "가장 좁은 연속 구간"을 찾는다.
 *
 * win_count 만 사용하므로, 막대 높이(count)가 필터된 표본이고 낙찰이 전체
 * 표본인 상황에서도 결과가 오염되지 않는다.
 *
 * 반환 null 인 경우:
 *   - 낙찰 데이터가 없음
 *   - 구간이 전체 폭의 대부분을 덮음 (= 집중이라 부를 수 없음)
 */
export function findWinZone(
  bins: OffsetBucket[],
  targetRatio: number = WIN_ZONE_TARGET_RATIO,
): WinZone | null {
  if (!bins.length) return null;
  if (targetRatio <= 0 || targetRatio > 1) targetRatio = WIN_ZONE_TARGET_RATIO;

  const totalWins = bins.reduce((s, b) => s + b.win_count, 0);
  if (totalWins === 0) return null;

  const need = totalWins * targetRatio;

  // 투 포인터로 최소 폭 윈도우 탐색
  let best: { start: number; end: number } | null = null;
  let lo = 0;
  let acc = 0;

  for (let hi = 0; hi < bins.length; hi++) {
    acc += bins[hi].win_count;
    while (lo < hi && acc - bins[lo].win_count >= need) {
      acc -= bins[lo].win_count;
      lo++;
    }
    if (acc >= need && (best === null || hi - lo < best.end - best.start)) {
      best = { start: lo, end: hi };
    }
  }
  if (!best) return null;

  let { start, end } = best;

  // 집중도 판정은 "실제로 찾은 최소 구간" 기준으로 한다.
  // 아래 시각화용 확장을 먼저 반영하면 판정이 왜곡된다.
  const foundWins = bins.slice(start, end + 1).reduce((s, b) => s + b.win_count, 0);
  const foundWidth = end - start + 1;
  // 집중도 = (foundWins/totalWins) / (foundWidth/bins.length).
  // 나눗셈으로 비교하면 0.6/0.4 가 1.4999999999999998 이 되어 경계에서 뒤집힌다.
  // 양변에 분모를 곱해 정수 비교로 만든다.
  if (foundWins * bins.length < WIN_ZONE_MIN_CONCENTRATION * totalWins * foundWidth) {
    return null;
  }

  // 단일 bin 이면 ReferenceArea 폭이 0 이 되어 안 보이므로 좌우로 한 칸씩 넓힌다
  if (start === end) {
    start = Math.max(0, start - 1);
    end = Math.min(bins.length - 1, end + 1);
  }

  const binCount = end - start + 1;
  const wins = bins.slice(start, end + 1).reduce((s, b) => s + b.win_count, 0);
  const ratio = (wins / totalWins) * 100;
  const widthRatio = (binCount / bins.length) * 100;

  return {
    from: bins[start].offset_pct,
    to: bins[end].offset_pct,
    startIndex: start,
    endIndex: end,
    wins,
    totalWins,
    ratio,
    binCount,
    totalBins: bins.length,
    widthRatio,
    concentration: ratio / widthRatio,
  };
}

export interface ZoneWinRate {
  /** 구간 내 참여자 대비 낙찰 비율 (%) */
  inZoneRate: number;
  /** 구간 밖 참여자 대비 낙찰 비율 (%) */
  outZoneRate: number;
  /** inZoneRate / outZoneRate */
  multiple: number;
}

/**
 * 집중 구간 안팎의 "참여자 대비 낙찰 비율"을 비교한다.
 *
 * 주의: count 와 win_count 가 같은 표본에서 왔을 때만 유효하다.
 * 필터가 걸려 막대는 발주처 표본, 낙찰은 전체 표본인 상황에서는
 * 전체 낙찰수 ÷ 필터된 참여수가 되어 무의미하다.
 * 호출부에서 winRateIsBroader() 로 먼저 걸러야 한다.
 */
export function zoneWinRate(bins: OffsetBucket[], zone: WinZone): ZoneWinRate | null {
  const inBins = bins.slice(zone.startIndex, zone.endIndex + 1);
  const inCount = inBins.reduce((s, b) => s + b.count, 0);
  const inWins = inBins.reduce((s, b) => s + b.win_count, 0);

  const totalCount = bins.reduce((s, b) => s + b.count, 0);
  const totalWins = bins.reduce((s, b) => s + b.win_count, 0);

  const outCount = totalCount - inCount;
  const outWins = totalWins - inWins;

  if (inCount === 0 || outCount === 0 || outWins === 0) return null;

  const inZoneRate = (inWins / inCount) * 100;
  const outZoneRate = (outWins / outCount) * 100;

  return { inZoneRate, outZoneRate, multiple: inZoneRate / outZoneRate };
}

// ── 표본 레벨 표시 ──────────────────────────────────────────────────────


/** result 가 아직 없을 때 쓰는 빈 품질 정보 */
export const DEFAULT_QUALITY: DistributionQuality = {
  total_bids: 0,
  distribution_level: "global",
  distribution_label: null,
  sample_notices: 0,
  win_rate_level: "global",
  win_rate_bids: 0,
};

export interface ScopeBadge {
  /** 배지에 적을 짧은 문구 */
  text: string;
  /** 표본이 좁을수록(=발주처에 가까울수록) 신뢰도가 높다는 뜻의 톤 */
  tone: "specific" | "broad";
  /** 배지 옆/툴팁에 붙일 설명 */
  hint: string;
}

/**
 * data_quality 를 사람이 읽는 배지 문구로 바꾼다.
 *
 * 사용자가 발주처를 입력했는데 그래프가 안 변했다면, 그건 버그가 아니라
 * 그 발주처의 표본이 부족해 상위 레벨로 폴백했다는 뜻이다. 그 사실을
 * 숨기지 않고 화면에 드러내는 게 이 배지의 목적이다.
 */
export function describeScope(dq: DistributionQuality): ScopeBadge {
  const notices = dq.sample_notices;

  switch (dq.distribution_level) {
    case "client":
      return {
        text: `${dq.distribution_label} 기준`,
        tone: "specific",
        hint: `이 발주처 공고 ${notices}건의 참여 분포입니다.`,
      };
    case "region":
      return {
        text: `${dq.distribution_label} 지역 기준`,
        tone: "broad",
        hint: `발주처 표본이 부족해 지역 단위로 넓혔습니다 (공고 ${notices}건).`,
      };
    default:
      return {
        text: "전체 기준",
        tone: "broad",
        hint: `발주처·지역·공종 모두 표본이 부족해 전체 분포를 씁니다 (공고 ${notices}건).`,
      };
  }
}

/**
 * 낙찰 빈도가 막대 높이와 다른 표본에서 왔는지 여부.
 * 참이면 "막대는 발주처, 낙찰률은 전체" 라는 설명이 필요하다.
 */
export function winRateIsBroader(dq: DistributionQuality): boolean {
  return dq.distribution_level !== dq.win_rate_level;
}

// ── 추천 투찰가 ─────────────────────────────────────────────────────────

/**
 * 후보가 되기 위한 최소 낙찰 표본.
 *
 * 낙찰 빈도는 wins/count 라 count 가 작을수록 튄다. 참여 3건 중 1건이 낙찰된
 * 꼬리 bin 은 33% 로 계산되어 어떤 정상 bin 보다도 높게 나온다. count 에 하한을
 * 거는 대신 **낙찰 건수**에 거는 이유는, bin 의 count 가 필터된 표본이고
 * 낙찰은 전체 표본이라 둘의 분모가 다르기 때문이다 (winRateIsBroader 참고).
 */
const MIN_WIN_SAMPLE = 5;

export interface BestBin {
  /** 추천 offset (%) */
  offset_pct: number;
  /** offset 을 환산한 투찰가 (원) */
  estimated_price: number;
  /** 해당 구간 과거 낙찰 빈도 (%) */
  historical_win_rate: number;
  /** 해당 구간 낙찰 건수 */
  win_count: number;
  /** 낙찰 빈도 계산에 쓰인 참여 건수 (전체 표본 기준, 역산값) */
  sample_count: number;
  /** 전체 평균 낙찰 빈도 대비 배수. 계산 불가면 null */
  multiple: number | null;
}

/**
 * 과거 낙찰 빈도가 가장 높았던 구간을 찾아 투찰가로 환산한다.
 *
 * **예측이 아니다.** 사정률은 복수예비가격 구조가 만드는 난수라 예측 대상이
 * 아니고(md/design/2026-05-29-distribution-engine-analysis.md), 이 값은 과거
 * 분포에서 가장 유리했던 자리를 금액으로 바꿔 놓은 것일 뿐이다. 개찰 전까지
 * 예정가격이 ±2~3% 흔들리므로 호출부는 그 사실을 함께 보여야 한다.
 *
 * 낙찰 **건수**(win_count)가 아니라 **빈도**(historical_win_rate)로 고르는 이유:
 * 낙찰이 많이 나온 구간은 대개 참여자가 많이 몰린 구간이라, 건수로 고르면
 * "남들 많이 가는 자리"를 되돌려줄 뿐 알파가 없다. 참여 대비 비율로 재야
 * "남들 대비 내가 이길 자리"가 된다.
 *
 * @param bins prepareDistribution() 결과 (꼬리 클램프가 끝난 표시 범위)
 * @param basePrice 기초금액 (원)
 * @param lowerLimitRate 법정 낙찰하한율 (실효 하한율이 아니다)
 * @param aValue A값 (원)
 * @returns 후보가 없으면 null — 억지로 숫자를 만들지 않는다
 */
export function findBestWinRateBin(
  bins: OffsetBucket[],
  basePrice: number,
  lowerLimitRate: number,
  aValue: number = 0,
): BestBin | null {
  if (!bins.length || !(basePrice > 0)) return null;

  const rated = bins.filter(
    (b) => b.historical_win_rate !== null && b.historical_win_rate > 0,
  );

  // 전체 평균 낙찰 빈도. bin 의 count 는 필터된 표본이라 쓸 수 없으므로,
  // 낙찰 빈도(전체 표본 기준)에서 분모를 역산해 같은 표본끼리 비교한다.
  let baseWins = 0;
  let baseCount = 0;
  for (const b of rated) {
    baseWins += b.win_count;
    baseCount += b.win_count / (b.historical_win_rate! / 100);
  }
  const overallRate = baseCount > 0 ? (baseWins / baseCount) * 100 : 0;

  let best: OffsetBucket | null = null;
  for (const b of rated) {
    if (b.win_count < MIN_WIN_SAMPLE) continue;
    if (
      best === null ||
      b.historical_win_rate! > best.historical_win_rate! ||
      // 동률이면 offset 이 높은 쪽 — 같은 확률이면 비싸게 받는 게 낫다
      (b.historical_win_rate! === best.historical_win_rate! &&
        b.offset_pct > best.offset_pct)
    ) {
      best = b;
    }
  }
  if (best === null) return null;

  const rate = best.historical_win_rate!;
  const a = normalizeAValue(aValue, basePrice);

  return {
    offset_pct: best.offset_pct,
    // offset → 금액 역변환. A값 조정의 역이므로 (예정가격 − A) × rate + A
    estimated_price: Math.round(
      (basePrice - a) * (lowerLimitRate + best.offset_pct / 100) + a,
    ),
    historical_win_rate: rate,
    win_count: best.win_count,
    sample_count: Math.round(best.win_count / (rate / 100)),
    multiple: overallRate > 0 ? rate / overallRate : null,
  };
}

// ── 무효율 ↔ 기대 낙찰 교환 ─────────────────────────────────────────────

/**
 * 투찰 시점에는 예정가격을 모른다. 우리가 정하는 건 **금액**뿐이고,
 * 그 금액이 분포 위 어디에 떨어지는지는 개찰 때 사정률이 정한다.
 *
 *     착지 offset o'(k) = (기초−A)(r+o) / (k·기초−A) − r        (k = 사정률)
 *
 * 그래서 "offset +0.3%p 에 넣는다" 는 조준일 뿐 착지가 아니다.
 * 착지가 0 아래로 밀리면 하한가 미달로 **무효**다 — 등수 문제가 아니라 탈락이다.
 *
 * 이 절의 함수들은 그 두 가지를 숫자로 만든다: 조준 위치별 무효 확률과,
 * 무효까지 반영한 기대 낙찰 빈도.
 *
 * ⚠ 사정률의 중심은 1.0 으로 둔다. 계약법별 평균이 실측으로 갈리는 건 사실이지만
 *   (`app/engine/contract_law.py`), 그 중심을 옮기면 자사 투찰 151건 검정에서
 *   오히려 나빠졌다 (tasks.md T-020). 산포만 쓴다.
 */

/** bin 폭 (%p). 백엔드 히스토그램 해상도와 같아야 한다. */
const BIN_WIDTH_PCT = 0.1;

/** 표준정규 누적분포. Abramowitz–Stegun 7.1.26 (오차 < 1.5e-7) */
function normalCdf(z: number): number {
  const sign = z < 0 ? -1 : 1;
  const x = Math.abs(z) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * x);
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t +
      0.254829592) *
      t *
      Math.exp(-x * x);
  return 0.5 * (1 + sign * y);
}

/**
 * 조준한 offset 이 실제로 착지할 때의 산포 (%p).
 *
 *     do'/dk |k=1 = −(r + o) / (1 − A/기초)
 *
 * 즉 사정률 산포가 하한율만큼 증폭되어 offset 축으로 옮겨온다.
 * A값이 있으면 분모가 줄어 산포가 더 커진다 — A값이 클수록 착지가 더 흔들린다.
 *
 * @param prepriceSdPct 사정률 표준편차 (%). 응답의 `preprice_sd_pct`
 * @param lowerLimitRate 법정 낙찰하한율
 * @param aimOffsetPct 조준 offset (%p)
 * @returns 착지 offset 의 표준편차 (%p). 산포를 모르면 0
 */
export function landingSdPct(
  prepriceSdPct: number,
  lowerLimitRate: number,
  basePrice: number,
  aValue: number,
  aimOffsetPct: number,
): number {
  if (!(prepriceSdPct > 0) || !(basePrice > 0)) return 0;
  const a = normalizeAValue(aValue, basePrice);
  return (prepriceSdPct * (lowerLimitRate + aimOffsetPct / 100)) / (1 - a / basePrice);
}

/**
 * 조준한 offset 이 하한선 아래로 밀릴 확률 (%) = 하한가 미달 무효 확률.
 *
 * 산포가 0 이면(계약법 불명 등) 확률이 아니라 결정론이다 — 0 또는 100.
 */
export function invalidProbability(aimOffsetPct: number, landingSd: number): number {
  if (!(landingSd > 0)) return aimOffsetPct >= 0 ? 0 : 100;
  return normalCdf(-aimOffsetPct / landingSd) * 100;
}

/**
 * 조준한 offset 의 기대 낙찰 빈도 (%).
 *
 * 착지 분포로 bin 별 과거 낙찰 빈도를 가중평균한다. 무효(착지 < 0)는 낙찰 0 이므로
 * 자연히 빠진다 — 무효 확률이 이미 이 값에 녹아 있다.
 *
 * **하한 미달 bin 은 낙찰 빈도가 찍혀 있어도 버린다.** 하한가 미달은 무효라
 * 물리적으로 낙찰될 수 없고, 거기 찍힌 값은 하한율 오염의 잔재다
 * (실측 낙찰자 15,207명 중 음수 offset 80명 = 0.5%).
 */
export function expectedWinRate(
  bins: OffsetBucket[],
  aimOffsetPct: number,
  landingSd: number,
): number {
  const half = BIN_WIDTH_PCT / 2;
  let sum = 0;
  for (const b of bins) {
    if (b.offset_pct < 0) continue;
    const rate = b.historical_win_rate;
    if (rate === null || rate <= 0) continue;

    let p: number;
    if (!(landingSd > 0)) {
      p = Math.abs(b.offset_pct - aimOffsetPct) < half ? 1 : 0;
    } else {
      p =
        normalCdf((b.offset_pct + half - aimOffsetPct) / landingSd) -
        normalCdf((b.offset_pct - half - aimOffsetPct) / landingSd);
    }
    sum += p * rate;
  }
  return sum;
}

/** 조준 사다리 — 추천 자리에서 이만큼(%p) 위까지 올려본다 */
const TRADEOFF_STEPS = [0, 0.3, 0.5, 1.0];

export interface TradeoffRow {
  /** 조준 offset (%p) */
  offset_pct: number;
  /** 그 자리의 투찰가 (원) */
  estimated_price: number;
  /** 하한가 미달로 무효가 될 확률 (%) */
  invalid_pct: number;
  /** 무효까지 반영한 기대 낙찰 빈도 (%) */
  expected_win_pct: number;
  /** 추천 자리인지 */
  is_recommended: boolean;
}

export interface OffsetTradeoff {
  rows: TradeoffRow[];
  /** 착지 offset 의 산포 (%p) — 추천 자리 기준 */
  landing_sd_pct: number;
  /** 과거 참여자가 실제로 하한 미달이었던 비율 (%) */
  market_invalid_pct: number;
}

/**
 * 조준 위치를 올렸을 때 무효율과 기대 낙찰이 어떻게 교환되는지 표로 만든다.
 *
 * 실측(참여 580만 건)에서 이 교환은 **한쪽으로 기운다**: 무효를 줄이려고 올리면
 * 기대 낙찰이 더 빨리 떨어진다. 하한선에 붙이는 게 기대값 기준으로는 최선이고,
 * 무효 40~50% 는 이 시장의 정상 비용이다. 다만 +0.3%p 까지는 기대 낙찰이 거의
 * 안 떨어지면서 무효율만 크게 준다 — 그 구간이 실질적인 선택지다.
 *
 * @param baseOffsetPct 추천 자리 (findBestWinRateBin 결과)
 * @returns 사정률 산포나 기초금액이 없으면 null — 없는 근거로 확률을 내지 않는다
 */
export function buildOffsetTradeoff(
  bins: OffsetBucket[],
  basePrice: number,
  lowerLimitRate: number,
  aValue: number,
  prepriceSdPct: number,
  baseOffsetPct: number,
): OffsetTradeoff | null {
  if (!bins.length || !(basePrice > 0) || !(prepriceSdPct > 0)) return null;

  const a = normalizeAValue(aValue, basePrice);

  const rows: TradeoffRow[] = TRADEOFF_STEPS.map((step, i) => {
    const offset = Math.round((baseOffsetPct + step) * 10) / 10;
    const sd = landingSdPct(prepriceSdPct, lowerLimitRate, basePrice, aValue, offset);
    return {
      offset_pct: offset,
      // offset → 금액 역변환. A값 조정의 역이므로 (예정가격 − A) × rate + A
      estimated_price: Math.round((basePrice - a) * (lowerLimitRate + offset / 100) + a),
      invalid_pct: invalidProbability(offset, sd),
      expected_win_pct: expectedWinRate(bins, offset, sd),
      is_recommended: i === 0,
    };
  });

  const total = bins.reduce((s, b) => s + b.count, 0);
  const below = bins.filter((b) => b.offset_pct < 0).reduce((s, b) => s + b.count, 0);

  return {
    rows,
    landing_sd_pct: landingSdPct(
      prepriceSdPct,
      lowerLimitRate,
      basePrice,
      aValue,
      baseOffsetPct,
    ),
    market_invalid_pct: total > 0 ? (below / total) * 100 : 0,
  };
}
