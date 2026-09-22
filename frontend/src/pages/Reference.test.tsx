import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Reference from "@/pages/Reference";
import { GLOSSARY, GROUP_LABEL } from "@/lib/glossary";
import { DECISIONS, PAPERS, SOURCE_LINKS, LIMIT_RATE_TABLE } from "@/lib/reference";

function renderPage() {
  return render(
    <MemoryRouter>
      <Reference />
    </MemoryRouter>,
  );
}

describe("도감 페이지", () => {
  it("다섯 섹션을 모두 그린다", () => {
    renderPage();
    for (const heading of ["용어 사전", "제도 규칙", "근거 문헌", "출처 링크", "이 엔진이 내린 판단"]) {
      expect(screen.getAllByText(new RegExp(heading)).length).toBeGreaterThan(0);
    }
  });

  it("용어는 분류별로 묶여 전부 나온다 — 툴팁과 같은 사전을 쓴다", () => {
    renderPage();
    for (const label of Object.values(GROUP_LABEL)) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    for (const e of Object.values(GLOSSARY)) {
      expect(screen.getAllByText(e.term).length, e.term).toBeGreaterThan(0);
    }
  });

  it("용어를 펼치면 뜻·왜·어디서 보이나가 나온다", () => {
    renderPage();
    // 접힌 상태에서는 한 줄 요약만 있고 산식·왜·어디서는 없다 — 30개를 다 펼치면 읽을 수가 없다
    expect(screen.queryByText(GLOSSARY.a_value.why)).not.toBeInTheDocument();
    // 접힌 행의 이름은 "용어 + 한 줄 요약" 이라, 다른 용어의 요약에 든 'A값' 과 갈리려면 앞머리로 잡는다
    fireEvent.click(screen.getByRole("button", { name: /^A값/ }));
    expect(screen.getByText(GLOSSARY.a_value.what)).toBeInTheDocument();
    expect(screen.getByText(GLOSSARY.a_value.why)).toBeInTheDocument();
    expect(screen.getByText(GLOSSARY.a_value.where)).toBeInTheDocument();
  });

  it("하한율 개정표는 변경 전·후를 나란히 보인다 — 옛 값을 지우면 과거 데이터를 못 읽는다", () => {
    renderPage();
    for (const row of LIMIT_RATE_TABLE) {
      expect(screen.getByText(row.scope)).toBeInTheDocument();
      expect(screen.getAllByText(row.before).length).toBeGreaterThan(0);
      expect(screen.getAllByText(row.after).length).toBeGreaterThan(0);
    }
  });

  it("논문은 주장과 우리 데이터의 대조 결과를 함께 보인다", () => {
    renderPage();
    for (const p of PAPERS) {
      expect(screen.getByText(p.title)).toBeInTheDocument();
      expect(screen.getByText(p.claim)).toBeInTheDocument();
      expect(screen.getByText(p.ours)).toBeInTheDocument();
    }
    // 재현된 것과 불일치한 것이 섞여 있다 — 한쪽만 싣지 않는다
    expect(screen.getAllByText("재현됨").length).toBeGreaterThan(0);
    expect(screen.getAllByText("불일치").length).toBeGreaterThan(0);
  });

  it("출처는 새 탭으로 열리는 외부 링크다", () => {
    renderPage();
    for (const s of SOURCE_LINKS) {
      const a = screen.getByRole("link", { name: new RegExp(s.label.slice(0, 10).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) });
      expect(a).toHaveAttribute("href", s.url);
      expect(a).toHaveAttribute("target", "_blank");
      expect(a).toHaveAttribute("rel", expect.stringContaining("noopener"));
    }
  });

  it("판단마다 근거 수치와 '하지 말아야 할 것' 이 붙는다", () => {
    renderPage();
    for (const d of DECISIONS) {
      expect(screen.getByText(d.title)).toBeInTheDocument();
      expect(screen.getByText(d.dont)).toBeInTheDocument();
      for (const e of d.evidence) {
        expect(screen.getByText(e)).toBeInTheDocument();
      }
    }
  });
});

describe("자료 무결성", () => {
  it("출처 링크는 전부 https 이고 중복이 없다", () => {
    const urls = SOURCE_LINKS.map((s) => s.url);
    for (const u of urls) expect(u).toMatch(/^https:\/\//);
    expect(new Set(urls).size).toBe(urls.length);
  });

  it("용어 이름은 중복되지 않는다 — 같은 이름이 둘이면 툴팁이 어느 쪽인지 알 수 없다", () => {
    const terms = Object.values(GLOSSARY).map((e) => e.term);
    expect(new Set(terms).size).toBe(terms.length);
  });

  it("모든 용어에 분류가 있다", () => {
    for (const [key, e] of Object.entries(GLOSSARY)) {
      expect(Object.keys(GROUP_LABEL), key).toContain(e.group);
    }
  });
});
