import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, calculateBid: vi.fn() };
});

import { calculateBid, type BidResult } from "@/lib/api";
import BidCalculator from "@/pages/BidCalculator";

function makeResult(over: Partial<BidResult> = {}): BidResult {
  return {
    bid_notice_id: "R25BK00678040",
    mode: "auto",
    overridden_fields: [],
    g2b_fetch_status: "ok",
    fetched: {
      base_price: 1_000_000_000,
      client_name: "서울특별시",
      region: "서울",
      project_type: "실내건축",
      lower_limit_rate: 0.87745,
      participants: 394,
    },
    base_price: 1_000_000_000,
    strategy: "normal",
    // 사정률은 예측하지 않는다 — 전역 고정 상수(T-015)
    predicted_rate: 1.0015,
    // 산포는 계약법에서 따라온다. "서울특별시" → 지방계약 ±3% → MAD 0.005191
    contract_law: "local",
    mad_value: 0.005191,
    prediction_range: [0.996309, 1.006691],
    confidence_grade: "fixed",
    fallback_level: "fixed",
    bids: [
      { label: "Aggressive", rate_pct: 87.14, price_krw: 871_450_000, digit_filter_triggered: false, a_value: 0 },
      { label: "Normal", rate_pct: 87.32, price_krw: 873_200_000, digit_filter_triggered: true, a_value: 0 },
      { label: "Safe", rate_pct: 87.51, price_krw: 875_100_000, digit_filter_triggered: false, a_value: 12_000_000 },
    ],
    ...over,
  } as BidResult;
}

async function calculate() {
  fireEvent.change(screen.getByPlaceholderText("예: R25BK00678040"), {
    target: { value: "R25BK00678040" },
  });
  fireEvent.click(screen.getByRole("button", { name: "계산하기" }));
  await waitFor(() => expect(screen.getByText(/예정가격 추정:/)).toBeInTheDocument());
}

describe("BidCalculator", () => {
  beforeEach(() => vi.mocked(calculateBid).mockReset());

  it("요약에는 공고마다 달라지는 값만 둔다 — 고정 상수를 헤드라인에 두지 않는다", async () => {
    // 예전엔 "적용 사정률: 100.15% 고정값" 이 이 자리에 있었다. 어떤 공고를 넣어도
    // 같은 숫자가 떠서, 근거가 있는 값인데도 계산을 안 한 것처럼 읽혔다.
    vi.mocked(calculateBid).mockResolvedValue(makeResult());
    render(<BidCalculator />);
    await calculate();

    // 예정가격 범위 = 기초금액 × (1 ± MAD).
    // 중심은 1.0 이다 — 고정 사정률 100.15% 가 아니다. 100.15 는 분포의 중심이
    // 아니라 하한가 미달을 피하려고 위로 올려 잡은 안전 여유값이라,
    // 그걸 중심으로 범위를 그리면 예정가격을 0.15%p 높게 오해하게 된다.
    expect(screen.getByText("994,809,000원 ~ 1,005,191,000원")).toBeInTheDocument();
    expect(screen.getByText("±0.52%p")).toBeInTheDocument();
    expect(screen.getByText("지방계약 ±3%")).toBeInTheDocument();
    expect(screen.queryByText("고정값 · 예측 아님")).not.toBeInTheDocument();
  });

  it("발주처가 바뀌면 산포와 예정가격 범위가 같이 좁아진다", async () => {
    // 복수예비가격 생성범위가 규정으로 갈린다 — 국가 ±2%, 지방 ±3%.
    // 추정이 아니라 제도 파라미터라 발주처만 보면 정해진다.
    vi.mocked(calculateBid).mockResolvedValue(
      makeResult({ contract_law: "national", mad_value: 0.003774 }),
    );
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText("996,226,000원 ~ 1,003,774,000원")).toBeInTheDocument();
    expect(screen.getByText("±0.38%p")).toBeInTheDocument();
    expect(screen.getByText("국가계약 ±2%")).toBeInTheDocument();
  });

  it("계약법을 모르면 넓게 잡고 그렇게 라벨한다 — 좁게 잡으면 확신을 과장한다", async () => {
    vi.mocked(calculateBid).mockResolvedValue(
      makeResult({ contract_law: "unknown", mad_value: 0.004856 }),
    );
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText("구분 불명")).toBeInTheDocument();
    expect(screen.getByText("±0.49%p")).toBeInTheDocument();
  });

  it("고정 사정률은 계산 기준으로만 각주에 남는다", async () => {
    // 완전히 숨기면 투찰가가 어디서 나온 숫자인지 설명이 안 된다.
    // 헤드라인에서 내리되 근거는 남긴다.
    vi.mocked(calculateBid).mockResolvedValue(makeResult());
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText(/맞히는 값이 아니다/)).toBeInTheDocument();
    // 산식 안내줄에도 같은 숫자가 찍히므로 개수로 확인한다
    expect(screen.getAllByText(/100\.15%/).length).toBeGreaterThan(0);
  });

  it("fallback_level 과 무관하게 같은 화면을 그린다", async () => {
    // 사정률 예측을 끈 뒤로 백엔드는 항상 "fixed" 를 돌려준다.
    // 예전엔 fallback_level 에 따라 "데이터 부족" / 신뢰도 배지를 갈랐는데,
    // 그게 "근거: 데이터 없음" 으로 찍혀 오해를 불렀다.
    for (const level of ["fixed", "default", "none"]) {
      vi.mocked(calculateBid).mockResolvedValue(makeResult({ fallback_level: level }));
      const { unmount } = render(<BidCalculator />);
      await calculate();

      expect(screen.getByText("994,809,000원 ~ 1,005,191,000원")).toBeInTheDocument();
      expect(screen.queryByText("데이터 부족")).not.toBeInTheDocument();
      expect(screen.queryByText(/^신뢰도/)).not.toBeInTheDocument();
      unmount();
    }
  });

  it("투찰가와 끝자리 회피·A값 표시를 그린다", async () => {
    vi.mocked(calculateBid).mockResolvedValue(makeResult());
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText("871,450,000원")).toBeInTheDocument();
    expect(screen.getByText("873,200,000원")).toBeInTheDocument();
    expect(screen.getByText("875,100,000원")).toBeInTheDocument();
    // 백엔드 필드명이 digit_filter_triggered 라 이전에는 한 번도 안 떴다
    expect(screen.getByText("끝자리 회피 적용됨")).toBeInTheDocument();
    expect(screen.getByText("A값 12,000,000원 반영")).toBeInTheDocument();
  });
});
