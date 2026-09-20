import { findBestAim, prepareDistribution } from "@/lib/distribution";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { cloneElement, type ReactElement } from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── recharts ResponsiveContainer 는 jsdom 에서 크기가 0 이라 아무것도 그리지 않는다.
//    고정 크기를 주입해 실제 SVG 가 렌더되게 한다.
vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 800, height: 360 }),
  };
});

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getBidDistribution: vi.fn() };
});

import { getBidDistribution, type DistributionResult } from "@/lib/api";
import BidDistribution from "@/pages/BidDistribution";

// ── 픽스처 ──────────────────────────────────────────────────────────────

/** 낙찰이 -0.8% ~ -0.5% 에 몰린 현실적인 분포 */
function makeResult(over: Partial<DistributionResult> = {}): DistributionResult {
  const wins: Record<string, number> = {
    "-1.2": 1, "-0.8": 10, "-0.7": 9, "-0.6": 6, "-0.5": 8, "0": 5, "0.3": 2,
  };
  const distribution = Array.from({ length: 21 }, (_, i) => {
    const offset_pct = Math.round((-1.5 + i / 10) * 10) / 10;
    const win_count = wins[String(offset_pct)] ?? 0;
    const count = 1000;
    return { offset_pct, count, win_count, historical_win_rate: (win_count / count) * 100 };
  });

  return {
    bid_notice_id: "R25BK00678040",
    base_price: 100_000_000,
    lower_limit_rate: 0.87745,
    estimated_participants: 394,
    g2b_fetch_status: "ok",
    distribution,
    data_quality: {
      total_bids: 21_000,
      distribution_level: "global",
      distribution_label: null,
      sample_notices: 71,
      win_rate_level: "global",
      win_rate_bids: 21_000,
    },
    my_position: null,
    ...over,
  } as DistributionResult;
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BidDistribution />
    </QueryClientProvider>,
  );
}

async function loadDistribution() {
  fireEvent.change(screen.getByPlaceholderText("예: R25BK00678040"), {
    target: { value: "R25BK00678040" },
  });
  fireEvent.click(screen.getByRole("button", { name: "분포 조회" }));
  await waitFor(() => expect(screen.getByText(/기초금액:/)).toBeInTheDocument());
}

// ── 테스트 ──────────────────────────────────────────────────────────────

describe("BidDistribution", () => {
  beforeEach(() => {
    vi.mocked(getBidDistribution).mockReset();
  });

  it("차트가 런타임 오류 없이 렌더된다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    const { container } = renderPage();
    await loadDistribution();

    // 이중축 ComposedChart 가 실제로 그려졌는지
    expect(container.querySelector(".recharts-surface")).toBeTruthy();
    expect(container.querySelectorAll(".recharts-bar").length).toBeGreaterThan(0);
  });

  it("낙찰 건수 라인이 보조축으로 그려진다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    const { container } = renderPage();
    await loadDistribution();

    // 막대에 뭉개지지 않도록 별도 축에 그리는 라인
    const line = container.querySelector(".recharts-line-curve");
    expect(line).toBeTruthy();
    expect(line?.getAttribute("d")).toBeTruthy();

    // 축이 둘이어야 한다 (왼쪽 참여자 / 오른쪽 낙찰)
    expect(container.querySelectorAll(".recharts-yAxis").length).toBe(2);
  });

  it("낙찰 집중 구간 밴드가 그려진다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    const { container } = renderPage();
    await loadDistribution();

    const area = container.querySelector(".recharts-reference-area");
    expect(area).toBeTruthy();
    // recharts 는 <rect> 가 아니라 <path class="recharts-reference-area-rect"> 로 그린다
    const shape = area?.querySelector(".recharts-reference-area-rect");
    expect(shape?.getAttribute("x1")).toBe("-0.8%");
    expect(shape?.getAttribute("x2")).toBe("-0.6%");
    // 폭이 0 이면 화면에서 안 보인다
    expect(Number(shape?.getAttribute("width"))).toBeGreaterThan(0);
  });

  it("집중 구간 요약과 배수 비교를 표시한다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    renderPage();
    await loadDistribution();

    expect(screen.getByText(/과거 낙찰의/)).toBeInTheDocument();
    // 60% 를 담는 최소 구간은 -0.8 ~ -0.6 (10+9+6 = 25건 / 전체 41건)
    expect(screen.getByText("-0.8% ~ -0.6%")).toBeInTheDocument();
    expect(screen.getByText(/낙찰 25건 \/ 전체 41건/)).toBeInTheDocument();
    expect(screen.getByText("9.4배")).toBeInTheDocument();
    // "낙찰 확률이 아니라 과거 위치다" 라는 설명 문구는 두지 않는다 —
    // 쓰는 사람이 이미 아는 내용이라 자리만 차지했다. 표본이 충분하고
    // 같은 표본에서 나온 숫자면 각주 자체가 뜨지 않아야 한다.
    expect(screen.queryByText(/낙찰 확률이 아닙니다/)).not.toBeInTheDocument();
    expect(screen.queryByText(/참고용으로만/)).not.toBeInTheDocument();
    expect(screen.queryByText(/전체 표본 기준/)).not.toBeInTheDocument();
  });

  it("막대와 낙찰 표본이 다르면 배수 비교를 숨긴다", async () => {
    // 발주처로 좁힌 막대 + 전체 표본 낙찰 → 분모가 달라 배수가 무의미하다
    vi.mocked(getBidDistribution).mockResolvedValue(
      makeResult({
        data_quality: {
          total_bids: 2_000,
          distribution_level: "client",
          distribution_label: "서울특별시",
          sample_notices: 40,
          win_rate_level: "global",
          win_rate_bids: 42_000,
        },
      } as Partial<DistributionResult>),
    );
    renderPage();
    await loadDistribution();

    expect(screen.getByText(/과거 낙찰의/)).toBeInTheDocument();
    expect(screen.queryByText(/구간 밖/)).not.toBeInTheDocument();
    expect(screen.getByText(/낙찰 위치는 전체 표본 기준입니다/)).toBeInTheDocument();
  });

  it("낙찰이 흩어져 있으면 밴드 대신 안내를 표시한다", async () => {
    const flat = makeResult();
    flat.distribution = flat.distribution.map((b) => ({
      ...b,
      win_count: 2,
      historical_win_rate: 0.2,
    }));
    vi.mocked(getBidDistribution).mockResolvedValue(flat);
    const { container } = renderPage();
    await loadDistribution();

    expect(screen.getByText(/몰려 있지 않습니다/)).toBeInTheDocument();
    expect(container.querySelector(".recharts-reference-area")).toBeFalsy();
  });

  it("투찰가를 넣으면 내 위치와 집중 구간의 관계를 보여준다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    renderPage();
    await loadDistribution();

    // offset -0.6% → 집중 구간(-0.8 ~ -0.5) 안
    const price = Math.round(100_000_000 * (0.87745 - 0.006));
    fireEvent.change(screen.getByPlaceholderText("예: 871450000"), {
      target: { value: String(price) },
    });

    await waitFor(() =>
      expect(screen.getByText(/내 위치가 낙찰 집중 구간 안입니다/)).toBeInTheDocument(),
    );
  });

  it("집중 구간 밖이면 몇 %p 떨어져 있는지 알려준다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    renderPage();
    await loadDistribution();

    // offset +0.2% → 구간(-0.8 ~ -0.5)보다 위
    const price = Math.round(100_000_000 * (0.87745 + 0.002));
    fireEvent.change(screen.getByPlaceholderText("예: 871450000"), {
      target: { value: String(price) },
    });

    await waitFor(() => expect(screen.getByText(/높습니다/)).toBeInTheDocument());
  });

  it("추천 투찰가를 금액으로 보여준다", async () => {
    // 픽스처의 낙찰 빈도 최대 구간은 -0.8% (참여 1000건 중 낙찰 10건 = 1%)
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    renderPage();
    await loadDistribution();

    expect(screen.getByText("추천 투찰가")).toBeInTheDocument();
    // (기초금액 − A) × (하한율 + offset) + A, A값 없음
    const expected = Math.round(100_000_000 * (0.87745 - 0.008));
    expect(screen.getByText(expected.toLocaleString())).toBeInTheDocument();
  });

  it("발주처 σ 가 있으면 추천가는 발주처 기준 고정 조준이다", async () => {
    const result = makeResult({ preprice_sd_pct: 0.549 } as any);
    vi.mocked(getBidDistribution).mockResolvedValue(result);
    renderPage();
    await loadDistribution();

    const aim = findBestAim(
      prepareDistribution(result.distribution).bins,
      result.base_price,
      result.lower_limit_rate,
      0,
      0.549,
    )!;
    expect(aim).not.toBeNull();
    expect(aim.offset_pct).toBeGreaterThanOrEqual(0);
    expect(screen.getByText(/이 발주처 기준 조준/)).toBeInTheDocument();
    // 카드와 교환표 추천 행 두 곳에 같은 금액이 찍힌다 — 그게 의도다
    expect(screen.getAllByText(aim.estimated_price.toLocaleString()).length).toBeGreaterThanOrEqual(2);
    // 교환표의 추천 행도 같은 자리를 가리킨다
    const row = screen.getByText("추천").closest("tr")!;
    expect(row.textContent).toContain(aim.estimated_price.toLocaleString());
  });

  it("낙찰 표본이 모자라면 추천 카드를 그리지 않는다", async () => {
    // 모든 구간의 낙찰이 5건 미만 — 근거가 없으면 숫자를 내지 않는다
    const thin = Array.from({ length: 21 }, (_, i) => {
      const offset_pct = Math.round((-1.5 + i / 10) * 10) / 10;
      const win_count = i % 3;
      return { offset_pct, count: 1000, win_count, historical_win_rate: win_count / 10 };
    });
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult({ distribution: thin }));
    renderPage();
    await loadDistribution();

    expect(screen.queryByText("추천 투찰가")).not.toBeInTheDocument();
  });

  it("붙여넣기가 인식되지 않으면 오류 문구를 보여준다", async () => {
    vi.mocked(getBidDistribution).mockResolvedValue(makeResult());
    renderPage();

    fireEvent.click(screen.getByText(/info21c 공고 텍스트 붙여넣기/));
    fireEvent.change(screen.getByPlaceholderText(/Ctrl\+A/), {
      target: { value: "관련 없는 텍스트" },
    });

    expect(screen.getByText(/인식된 필드가 없습니다/)).toBeInTheDocument();
  });
});
