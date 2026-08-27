import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryState, SERVER_ERROR_HINT } from "@/components/QueryState";

describe("QueryState", () => {
  it("로딩 중이면 자식 대신 스피너를 보여준다", () => {
    const { container } = render(
      <QueryState isLoading error={null}>
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.queryByText("내용")).not.toBeInTheDocument();
    expect(container.querySelector(".animate-spin")).toBeTruthy();
  });

  it("실패하면 백지 대신 안내를 보여준다", () => {
    render(
      <QueryState isLoading={false} error={new Error("Connection refused")}>
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.getByText("데이터를 불러오지 못했습니다")).toBeInTheDocument();
    expect(screen.getByText("Connection refused")).toBeInTheDocument();
    expect(screen.queryByText("내용")).not.toBeInTheDocument();
  });

  it("메시지 없는 오류는 기본 안내로 대체한다", () => {
    render(
      <QueryState isLoading={false} error={{}}>
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.getByText(SERVER_ERROR_HINT)).toBeInTheDocument();
  });

  it("onRetry 를 주면 다시 시도 버튼이 동작한다", () => {
    const onRetry = vi.fn();
    render(
      <QueryState isLoading={false} error={new Error("x")} onRetry={onRetry}>
        <p>내용</p>
      </QueryState>,
    );
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("onRetry 가 없으면 버튼을 그리지 않는다", () => {
    render(
      <QueryState isLoading={false} error={new Error("x")}>
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.queryByRole("button", { name: "다시 시도" })).not.toBeInTheDocument();
  });

  it("비어 있으면 안내 문구를 보여준다", () => {
    render(
      <QueryState isLoading={false} error={null} isEmpty emptyMessage="아직 데이터가 없습니다">
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.getByText("아직 데이터가 없습니다")).toBeInTheDocument();
    expect(screen.queryByText("내용")).not.toBeInTheDocument();
  });

  it("정상이면 자식을 그대로 그린다", () => {
    render(
      <QueryState isLoading={false} error={null}>
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.getByText("내용")).toBeInTheDocument();
  });

  it("오류가 비어 있음보다 우선한다", () => {
    render(
      <QueryState isLoading={false} error={new Error("x")} isEmpty>
        <p>내용</p>
      </QueryState>,
    );
    expect(screen.getByText("데이터를 불러오지 못했습니다")).toBeInTheDocument();
  });
});
