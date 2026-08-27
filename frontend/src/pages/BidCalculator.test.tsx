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
    strategy: "normal",
    predicted_rate: 0.9987,
    mad_value: 0.0019,
    prediction_range: [0.9968, 1.0006],
    confidence_grade: "high",
    fallback_level: "client",
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
  await waitFor(() => expect(screen.getByText(/예측 사정률:/)).toBeInTheDocument());
}

describe("BidCalculator", () => {
  beforeEach(() => vi.mocked(calculateBid).mockReset());

  it("이력이 있으면 사정률과 예측 구간·신뢰도를 함께 보여준다", async () => {
    vi.mocked(calculateBid).mockResolvedValue(makeResult());
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText("99.87%")).toBeInTheDocument();
    expect(screen.getByText("(99.68% ~ 100.06%)")).toBeInTheDocument();
    expect(screen.getByText("신뢰도 높음")).toBeInTheDocument();
    expect(screen.getByText(/추첨으로 정해집니다/)).toBeInTheDocument();
  });

  it("이력이 없으면 1.0 을 숫자로 찍지 않고 데이터 부족이라고 말한다", async () => {
    vi.mocked(calculateBid).mockResolvedValue(
      makeResult({
        fallback_level: "default",
        predicted_rate: 1.0,
        prediction_range: [0.998, 1.002],
        confidence_grade: "low",
      }),
    );
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText("데이터 부족")).toBeInTheDocument();
    // 기준값이 정밀한 예측처럼 보이면 안 된다
    expect(screen.queryByText("100.00%")).not.toBeInTheDocument();
    expect(screen.queryByText(/^신뢰도/)).not.toBeInTheDocument();
    expect(screen.getByText(/예측이 아니라 하한율 기준 계산값/)).toBeInTheDocument();
  });

  it("fallback_level 이 none 이어도 같게 처리한다", async () => {
    vi.mocked(calculateBid).mockResolvedValue(
      makeResult({ fallback_level: "none", predicted_rate: 1.0 }),
    );
    render(<BidCalculator />);
    await calculate();

    expect(screen.getByText("데이터 부족")).toBeInTheDocument();
  });

  it("투찰가 3개와 끝자리 회피·A값 표시를 그린다", async () => {
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
