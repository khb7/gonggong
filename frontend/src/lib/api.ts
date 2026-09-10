const BASE_URL = import.meta.env.VITE_API_URL ?? "";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${url}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    const error: any = new Error(detail.detail || res.statusText);
    error.status = res.status;
    throw error;
  }
  return res.json();
}

// Types
export interface BidResult {
  bid_notice_id: string;
  mode: "auto" | "override";
  overridden_fields: string[];
  g2b_fetch_status: "ok" | "failed" | "mock";
  fetched: {
    base_price: number;
    client_name: string;
    region: string;
    project_type: string;
    lower_limit_rate: number;
    participants: number;
  };
  /** 계산에 실제로 쓴 기초금액(원). override 반영값이라 fetched.base_price 와 다를 수 있다 */
  base_price: number;
  strategy: "safe" | "normal" | "aggressive";
  /**
   * 투찰가 계산에 쓴 사정률. 예측이 아니라 전역 고정 상수(100.15%)다 — T-015.
   * **분포의 중심이 아니다.** 하한가 미달을 피하려고 위로 올려 잡은 안전 여유값이라,
   * 이 값을 중심으로 예정가격 범위를 그리면 안 된다. 중심은 1.0 이다.
   */
  predicted_rate: number;
  /** 발주처에서 판별한 계약법. 사정률 산포가 여기서 따라온다 */
  contract_law: "national" | "local" | "agency" | "unknown";
  /** 사정률 MAD. 계약법별 실측값이라 공고마다 다르다 */
  mad_value: number;
  /** [lower, upper] = predicted_rate ± MAD. 중심이 고정 사정률이라 표시용으로는 쓰지 않는다 */
  prediction_range: [number, number];
  confidence_grade: "high" | "medium" | "low";
  fallback_level: string;
  bids: {
    label: string;
    rate_pct: number;
    price_krw: number;
    /** 백엔드 필드명은 triggered 다. applied 로 읽으면 항상 undefined 가 된다 */
    digit_filter_triggered: boolean;
    a_value: number;
  }[];
}

export interface OverviewData {
  total_records: number;
  date_range: { start: string | null; end: string | null };
  last_collected: string | null;
  by_project_type: Record<string, number>;
}

export interface ClientStat {
  client_name: string;
  record_count: number;
  avg_adjustment_rate: number;
  avg_participants: number;
}

export interface DistributionData {
  bins: number[];
  counts: number[];
  total: number;
  median: number;
  mad: number;
  min_rate: number;
  max_rate: number;
}

export interface BackfillStatus {
  is_running: boolean;
  progress: {
    chunk_current: number;
    chunk_total: number;
    chunk_start: string;
    chunk_end: string;
    records_so_far: number;
  } | null;
  last_run: {
    started_at: string;
    completed_at: string | null;
    start_date: string;
    end_date: string;
    inserted: number;
    error: string | null;
  } | null;
}

// API functions
export function calculateBid(
  bid_notice_id: string,
  overrides?: Record<string, number | string | null>,
) {
  const body: any = { bid_notice_id };
  if (overrides) {
    const clean: Record<string, number | string> = {};
    for (const [k, v] of Object.entries(overrides)) {
      if (v != null && v !== "") clean[k] = v;
    }
    if (Object.keys(clean).length > 0) body.overrides = clean;
  }
  return request<BidResult>("/api/v1/bid/calculate", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getOverview() {
  return request<OverviewData>("/api/v1/stats/overview");
}

export function getClients() {
  return request<ClientStat[]>("/api/v1/stats/clients");
}

/**
 * 통계 분포 지표. 두 값은 전혀 다르고 자릿수도 다르다 — 섞으면 안 된다.
 *
 *   preprice = 예정가격 / 기초금액   중앙 0.999   ← 사정률. 복수예비가격이 만드는 제도적 난수
 *   award    = 낙찰가   / 기초금액   중앙 0.883   ← 낙찰률. 하한율 × 사정률에 가깝다
 */
export type DistributionMetric = "preprice" | "award";

export function getDistribution(
  projectType?: string,
  metric: DistributionMetric = "preprice",
) {
  const params = new URLSearchParams({ metric });
  if (projectType) params.set("project_type", projectType);
  return request<DistributionData>(`/api/v1/stats/distribution?${params}`);
}

export interface SchedulerStatus {
  enabled: boolean;
  collect_hour: number;
  next_run: string | null;
}

export function getBackfillStatus() {
  return request<BackfillStatus>("/api/v1/stats/backfill");
}

export function getSchedulerStatus() {
  return request<SchedulerStatus>("/api/v1/stats/scheduler");
}

export function startBackfill(start_date: string, end_date: string) {
  return request<{ accepted: boolean; message: string }>("/api/v1/stats/backfill", {
    method: "POST",
    body: JSON.stringify({ start_date, end_date }),
  });
}

// ── Distribution Engine ───────────────────────────────────────────────────

export interface OffsetBucket {
  offset_pct: number;
  count: number;
  win_count: number;
  historical_win_rate: number | null;
}

export interface BidPosition {
  offset_pct: number;
  estimated_price: number;
  percentile: number;
  historical_win_rate: number;
  sample_count: number;
}

/** 분포 계산에 쓰인 fallback 레벨 */
export type DistributionLevel = "client" | "region" | "global";

export interface DistributionQuality {
  /** 선택된 레벨의 참여자 수 (막대 높이의 합) */
  total_bids: number;
  /** 막대 높이(count)에 사용된 레벨 */
  distribution_level: DistributionLevel;
  /** 해당 레벨의 필터값. global이면 null */
  distribution_label: string | null;
  /** 선택된 레벨의 공고 수 — 레벨 채택 기준 */
  sample_notices: number;
  /** 낙찰 빈도 계산에 사용된 레벨. 표본 요구량이 달라 항상 global */
  win_rate_level: DistributionLevel;
  /** 낙찰 빈도 계산에 사용된 전체 참여자 수 */
  win_rate_bids: number;
}

export interface DistributionResult {
  bid_notice_id: string;
  base_price: number;
  /** 법정 낙찰하한율 (A값 제외 기준선) */
  lower_limit_rate: number;
  /** 계산에 반영된 A값 (원). 0이면 A값 없는 공고 */
  a_value: number;
  estimated_participants: number;
  /** 발주처 적용 계약법: "national"(±2%) | "local"(±3%) | "agency"(지방조달청·혼합) | "unknown" */
  contract_law: string;
  /**
   * 사정률 표준편차 (%). 투찰 시점에 예정가격을 모르므로 내 위치는 이 폭만큼 번져 있다.
   * 복수예비가격 생성범위가 규정으로 정해져 있어(국가 ±2% / 지방 ±3%) 추정값이 아니다.
   */
  preprice_sd_pct: number;
  g2b_fetch_status: string;
  distribution: OffsetBucket[];
  data_quality: DistributionQuality;
  my_position: BidPosition | null;
}

export function getBidDistribution(
  bid_notice_id: string,
  overrides?: Record<string, number | string | null>,
  my_bid_price?: number | null,
) {
  const body: Record<string, unknown> = { bid_notice_id };
  if (overrides) {
    const clean: Record<string, number | string> = {};
    for (const [k, v] of Object.entries(overrides)) {
      if (v != null && v !== "") clean[k] = v;
    }
    if (Object.keys(clean).length > 0) body.overrides = clean;
  }
  if (my_bid_price != null) body.my_bid_price = my_bid_price;
  return request<DistributionResult>("/api/v1/bid/distribution", {
    method: "POST",
    body: JSON.stringify(body),
  });
}
