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
  await waitFor(() => expect(screen.getByText(/적용 사정률:/)).toBeInTheDocument());
}

describe("BidCalculator", () => {
  beforeEach(() => vi.mocked(calculateBid).mockReset());

  it("사정률을 고정값으로 제시하고 예측이 아님을 명시한다", async () => {
    vi.mocked(calculateBid).mockResolvedValue(makeResult());
    render(<BidCalculator />);
    await calculate();

    // 산식 안내줄에도 같은 숫자가 찍히므로 개수로 확인한다
    expect(screen.getAllByText("99.87%").length).toBeGreaterThan(0);
    expect(screen.getByText("고정값 · 예측 아님")).toBeInTheDocument();
    expect(screen.getByText("99.68% ~ 100.06%")).toBeInTheDocument();
    expect(screen.getByText(/맞히는 값이 아니다/)).toBeInTheDocument();
  });

  it("fallback_level 과 무관하게 같은 화면을 그린다", async () => {
    // 사정률 예측을 끈 뒤로 백엔드는 항상 "fixed" 를 돌려준다.
    // 예전엔 fallback_level 에 따라 "데이터 부족" / 신뢰도 배지를 갈랐는데,
    // 그게 "근거: 데이터 없음" 으로 찍혀 오해를 불렀다.
    for (const level of ["fixed", "default", "none"]) {
      vi.mocked(calculateBid).mockResolvedValue(
        makeResult({ fallback_level: level, predicted_rate: 1.0015 }),
      );
      const { unmount } = render(<BidCalculator />);
      await calculate();

      expect(screen.getAllByText("100.15%").length).toBeGreaterThan(0);
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
