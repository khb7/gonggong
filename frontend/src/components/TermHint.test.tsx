import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TermHint } from "@/components/TermHint";
import { GLOSSARY } from "@/lib/glossary";

// 페이지 테스트는 App 의 TooltipProvider 없이 렌더한다 — TermHint 가 스스로 품어야 한다.
function renderHint(ui: React.ReactElement) {
  return render(ui);
}

describe("TermHint", () => {
  it("라벨 뒤에 ⓘ 버튼을 붙이고, 열기 전에는 정의를 보이지 않는다", () => {
    renderHint(<TermHint term="valid_rate">유효 (하한가 이상)</TermHint>);
    expect(screen.getByText("유효 (하한가 이상)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "유효율 설명" })).toBeInTheDocument();
    expect(screen.queryByText(GLOSSARY.valid_rate.what)).not.toBeInTheDocument();
  });

  it("탭(클릭)하면 뜻·산식·왜 세 줄이 뜬다 — 터치 기기에서도 열려야 한다", async () => {
    renderHint(<TermHint term="near_rate" />);
    fireEvent.click(screen.getByRole("button", { name: "근접률 설명" }));
    await waitFor(() => {
      expect(screen.getAllByText(GLOSSARY.near_rate.what).length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText(GLOSSARY.near_rate.formula).length).toBeGreaterThan(0);
    expect(screen.getAllByText(GLOSSARY.near_rate.why).length).toBeGreaterThan(0);
  });

  it("다시 클릭하면 닫힌다", async () => {
    renderHint(<TermHint term="a_value" />);
    const btn = screen.getByRole("button", { name: "A값 설명" });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getAllByText(GLOSSARY.a_value.what).length).toBeGreaterThan(0));
    fireEvent.click(btn);
    await waitFor(() => expect(screen.queryByText(GLOSSARY.a_value.what)).not.toBeInTheDocument());
  });
});

describe("GLOSSARY", () => {
  it("모든 항목에 이름과 한 문장 정의가 있다", () => {
    for (const [key, e] of Object.entries(GLOSSARY)) {
      expect(e.term, key).toBeTruthy();
      expect(e.what.length, key).toBeGreaterThan(10);
    }
  });
});
