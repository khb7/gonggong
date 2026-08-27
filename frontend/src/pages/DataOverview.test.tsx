import { describe, it, expect, vi, beforeEach } from "vitest";
import { cloneElement, type ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 800, height: 300 }),
  };
});

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, getOverview: vi.fn() };
});

import { getOverview, type OverviewData } from "@/lib/api";
import DataOverview from "@/pages/DataOverview";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DataOverview />
    </QueryClientProvider>,
  );
}

const FULL = {
  total_records: 42_184,
  date_range: { start: "2025-01-01", end: "2025-12-31" },
  last_collected: "2025-12-31",
  by_project_type: { 실내건축: 21_000, 조경: 21_184 },
} as OverviewData;

describe("DataOverview", () => {
  beforeEach(() => vi.mocked(getOverview).mockReset());

  // 조회 실패 시 백지가 되지 않고 안내가 뜨는 동작은 QueryState.test.tsx 에서 검증한다.
  // 여기서 재현하려 하면 React Query 의 실패 promise 가 러너에 unhandled rejection 으로
  // 잡혀 테스트가 깨진다 (렌더 자체는 정상 동작하는 것을 수동으로 확인함).

  it("수집된 데이터가 없으면 다음에 뭘 해야 하는지 알려준다", async () => {
    vi.mocked(getOverview).mockResolvedValue({
      total_records: 0,
      date_range: { start: null, end: null },
      last_collected: null,
      by_project_type: {},
    } as unknown as OverviewData);
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/아직 수집된 데이터가 없습니다/)).toBeInTheDocument(),
    );
  });

  it("데이터가 있으면 요약과 차트를 그린다", async () => {
    vi.mocked(getOverview).mockResolvedValue(FULL);
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText("42,184")).toBeInTheDocument());
    expect(screen.getByText("2025-01-01")).toBeInTheDocument();
    expect(container.querySelector(".recharts-bar")).toBeTruthy();
  });

  it("공종 정보가 없으면 빈 차트 대신 문구를 보여준다", async () => {
    vi.mocked(getOverview).mockResolvedValue({ ...FULL, by_project_type: {} });
    const { container } = renderPage();

    await waitFor(() => expect(screen.getByText("공종 정보가 없습니다.")).toBeInTheDocument());
    expect(container.querySelector(".recharts-bar")).toBeFalsy();
  });
});
