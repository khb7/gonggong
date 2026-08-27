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
 */
export function computeLocalPosition(
  myBidPrice: number,
  basePrice: number,
  lowerLimitRate: number,
  bins: OffsetBucket[],
  aValue: number = 0,
): LocalPosition | null {
  if (!bins.length || myBidPrice <= 0 || basePrice <= 0) return null;

  // A값이 예정가격(≈기초금액) 이상이면 이상값 — 무시하고 A값 없이 계산한다
  const a = aValue > 0 && aValue < basePrice ? aValue : 0;

  const adjustedRate = (myBidPrice - a) / (basePrice - a);
  const myOffsetPct = Math.round((adjustedRate - lowerLimitRate) * 1000) / 10;
  const key = toKey(myOffsetPct);

  const matching = bins.find((b) => toKey(b.offset_pct) === key);
  if (!matching) return null;

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
    case "type_bucket":
      return {
        text: `${dq.distribution_label} 공종 기준`,
        tone: "broad",
        hint: `발주처·지역 표본이 부족해 공종·금액구간으로 넓혔습니다 (공고 ${notices}건).`,
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
