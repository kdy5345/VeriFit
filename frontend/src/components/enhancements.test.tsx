import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { ScenarioComparison } from "./ScenarioComparison";
import { ProductCard } from "./ProductCard";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { askAgent, compareScenarios, restoreConversation } from "../lib/api";
import type { AskResponse, ProductResult, ScenarioResponse } from "../types/agent";

vi.mock("../lib/api", () => ({askAgent: vi.fn(), compareScenarios: vi.fn(), restoreConversation: vi.fn()}));

const product: ProductResult = {
  product_key: "p1", institution_name: "테스트은행", product_name: "검증적금", reserve_type: "fixed", term_months: 12,
  base_rate_bps: 200, achieved_rate_bps: 200, max_rate_bps: 300, after_tax_interest_won: 32994, maturity_amount_won: 3632994,
  eligibility_warning: false, eligibility_status: "satisfied", eligibility_reasons: [], potential_rate_bps: 300,
  potential_after_tax_interest_won: 49491, disclosed_month: "202609", updated_at: "2026-10-02T00:00:00Z", source_hash: "hash",
  bonuses: [{bonus_id: "salary", label: "급여이체", rate_bps: 100, satisfied: false, status: "unknown", evidence_quote: "급여이체 우대", exclusion_reason: null}],
};
const response: AskResponse = {
  thread_id: "thread-1", status: "completed", answer: "검증한 결과입니다.", products: [product], questions: [],
  extracted_profile: {monthly_deposit_won: 300000, term_months: 12, facts: {}}, used_fallback: false, retry_count: 0,
  verification_errors: [], disclaimer: "예상 금리는 확인이 필요합니다.", excluded_products: [],
  next_question: {code: "salary_transfer", question: "급여이체가 가능한가요?", interest_gain_won: 16497, affected_products: 1,
    missing_fields: ["satisfied"], explanation: "충족을 가정한 최대 추가 이자입니다."},
};
const comparison: ScenarioResponse = {
  baseline: {results: [product], excluded_results: []},
  scenarios: [{name: "변경 조건", evaluation: {results: [{...product, after_tax_interest_won: 49491}], excluded_results: []},
    deltas: [{product_key: "p1", product_name: "검증적금", baseline_rank: 1, scenario_rank: 1, after_tax_interest_delta_won: 16497}]}],
  disclaimer: "가정 비교입니다.",
};

beforeEach(() => {sessionStorage.clear(); vi.resetAllMocks();});
afterEach(cleanup);

describe("VeriFit 사용자 흐름", () => {
  it("입력 → 결과 → 추가 질문 → 후속 대화가 같은 thread를 사용한다", async () => {
    vi.mocked(askAgent).mockResolvedValue(response);
    render(<App />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("적금 조건 입력"), "월 30만 원 1년");
    await user.click(screen.getByRole("button", {name: "내 조건 분석하기"}));
    await screen.findByText("급여이체가 가능한가요?");
    expect(sessionStorage.getItem("verifit.thread")).toBe("thread-1");
    await user.type(screen.getByLabelText("적금 조건 입력"), "급여이체는 가능해요");
    await user.click(screen.getByRole("button", {name: "다시 계산"}));
    await waitFor(() => expect(askAgent).toHaveBeenLastCalledWith("급여이체는 가능해요", "thread-1", expect.any(AbortSignal)));
  });

  it("새로고침 후 서버 대화를 복원하고 새 비교에서 연결을 끊는다", async () => {
    sessionStorage.setItem("verifit.thread", "thread-1");
    vi.mocked(restoreConversation).mockResolvedValue(response);
    render(<App />);
    await screen.findByText("급여이체가 가능한가요?");
    expect(restoreConversation).toHaveBeenCalledWith("thread-1", expect.any(AbortSignal));
    await userEvent.click(screen.getByRole("button", {name: "새 비교"}));
    expect(sessionStorage.getItem("verifit.thread")).toBeNull();
    expect(screen.getByRole("button", {name: "내 조건 분석하기"})).toBeTruthy();
  });

  it("복원 실패를 사용자에게 표시한다", async () => {
    sessionStorage.setItem("verifit.thread", "missing");
    vi.mocked(restoreConversation).mockRejectedValue(new Error("저장된 대화를 찾지 못했습니다."));
    render(<App />);
    expect(await screen.findByText(/대화 복원 실패/)).toBeTruthy();
  });

  it("미확인을 미충족과 구분하고 근거에 같은 판정을 보여준다", () => {
    render(<ProductCard product={product} rank={1} onOpenEvidence={() => {}} />);
    expect(screen.getByText("미확인")).toBeTruthy();
    cleanup();
    render(<EvidenceDrawer product={product} onClose={() => {}} />);
    expect(screen.getByText(/판정에 필요한 정보가 부족/)).toBeTruthy();
    expect(screen.getByText(/원문 버전: hash/)).toBeTruthy();
  });

  it("가정 비교는 프로필을 복사하고 원래 조건을 변경하지 않는다", async () => {
    vi.mocked(compareScenarios).mockResolvedValue(comparison);
    const profile = response.extracted_profile!;
    render(<ScenarioComparison profile={profile} />);
    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("급여이체 가정"), "yes");
    await user.click(screen.getByRole("button", {name: "가정 비교하기"}));
    expect(await screen.findByText("+16,497원")).toBeTruthy();
    expect(compareScenarios).toHaveBeenCalledWith(profile, {...profile, facts: {salary_transfer: {satisfied: true}}}, expect.any(AbortSignal));
    expect(profile.facts).toEqual({});
  });

  it("비교 API 오류를 숨기지 않는다", async () => {
    vi.mocked(compareScenarios).mockRejectedValue(new Error("일시 오류"));
    render(<ScenarioComparison profile={response.extracted_profile!} />);
    await userEvent.click(screen.getByRole("button", {name: "가정 비교하기"}));
    expect((await screen.findByRole("alert")).textContent).toBe("일시 오류");
  });
});
