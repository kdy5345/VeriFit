import { useEffect, useRef, useState } from "react";
import type { ScenarioResponse, UserProfile } from "../types/agent";
import { compareScenarios } from "../lib/api";
import { formatWon, reserveLabel } from "../lib/format";
import { Field, Input, Select } from "./ui/Field";

export function ScenarioComparison({ profile }: { profile: UserProfile }) {
  const [amount, setAmount] = useState(String(profile.monthly_deposit_won));
  const [term, setTerm] = useState(String(profile.term_months));
  const [salary, setSalary] = useState("unchanged");
  const [result, setResult] = useState<ScenarioResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  useEffect(() => () => requestRef.current?.abort(), []);

  async function compare() {
    if (!Number.isSafeInteger(Number(amount)) || Number(amount) <= 0 || !Number.isInteger(Number(term)) || Number(term) < 1 || Number(term) > 60) {
      setError("월 납입액은 양의 정수, 기간은 1~60개월로 입력해 주세요.");
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true); setError(""); setResult(null);
    const facts = {...profile.facts};
    if (salary !== "unchanged") facts.salary_transfer = {...facts.salary_transfer, satisfied: salary === "yes"};
    try {
      const response = await compareScenarios(profile, {monthly_deposit_won: Number(amount), term_months: Number(term), facts}, controller.signal);
      if (!controller.signal.aborted) setResult(response);
    } catch (caught) {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "비교에 실패했습니다.");
    } finally {
      if (requestRef.current === controller && !controller.signal.aborted) setLoading(false);
    }
  }

  const scenario = result?.scenarios[0];
  return <div>
    <form onSubmit={(event) => {event.preventDefault(); void compare();}} className="grid gap-3 sm:grid-cols-3">
      <Field label="월 납입액 (원)"><Input type="number" inputMode="numeric" disabled={loading} min="1" step="1" value={amount} onChange={(e) => {setAmount(e.target.value); setResult(null);}} /></Field>
      <Field label="기간 (개월)"><Input type="number" inputMode="numeric" disabled={loading} min="1" max="60" step="1" value={term} onChange={(e) => {setTerm(e.target.value); setResult(null);}} /></Field>
      <Field label="급여이체 가정"><Select value={salary} disabled={loading} onChange={(e) => {setSalary(e.target.value); setResult(null);}}><option value="unchanged">지금 조건 그대로</option><option value="yes">가능하다고 가정</option><option value="no">불가능하다고 가정</option></Select></Field>
      <button type="submit" disabled={loading} className="min-h-12 rounded-2xl border-0 bg-background-fill-strong text-callout font-bold text-content transition-colors hover:bg-background-fill disabled:cursor-wait disabled:opacity-60 sm:col-span-3">{loading ? "다시 계산하는 중" : "가정 비교하기"}</button>
    </form>
    {error && <p role="alert" className="mb-0 mt-3 text-callout text-danger">{error}</p>}
    {scenario && <div className="mt-5" aria-live="polite">
      <p className="m-0 text-callout font-bold">월 {formatWon(Number(amount))}원, {term}개월로 바꾸면</p>
      <ul className="mb-0 mt-2 list-none divide-y divide-border-divider p-0">
        {scenario.evaluation.results.map((product) => {
          const delta = scenario.deltas.find((d) => d.product_key === product.product_key);
          const diff = delta?.after_tax_interest_delta_won;
          return <li key={product.product_key} className="flex items-center gap-3 py-3">
            <span className="min-w-0 flex-1">
              <span className="block truncate text-callout font-bold">{product.product_name}</span>
              <span className="flex flex-wrap gap-x-2 text-footnote text-content-assistive">
                <span>{product.institution_name}</span><span>{reserveLabel(product.reserve_type)}</span>
                <span>{delta?.baseline_rank ? `${delta.baseline_rank}위에서 ${delta.scenario_rank}위` : `새로 ${delta?.scenario_rank}위`}</span>
                {product.eligibility_status === "unknown" && <span className="text-danger">자격 확인 필요</span>}
              </span>
            </span>
            <span className="shrink-0 text-right tabular-nums">
              <span className="block text-callout font-bold">{formatWon(product.after_tax_interest_won)}원</span>
              <span className={`block text-footnote ${diff == null ? "text-content-assistive" : diff > 0 ? "text-brand" : diff < 0 ? "text-danger" : "text-content-assistive"}`}>{diff == null ? "비교 기준 없음" : `${diff > 0 ? "+" : ""}${formatWon(diff)}원`}</span>
            </span>
          </li>;
        })}
      </ul>
      {scenario.evaluation.results.length === 0 && <p className="text-callout text-content-assistive">바꾼 조건에 맞는 상품이 없어요.</p>}
      {scenario.evaluation.excluded_results.map((product) => <p key={product.product_key} className="mb-0 mt-2 text-footnote text-content-assistive">제외: {product.product_name}, {product.eligibility_reasons.join(", ")}</p>)}
      <p className="mb-0 mt-3 text-footnote leading-5 text-content-assistive">기간이 다르면 넣는 원금도 달라져요. 미확인 조건은 충족으로 바꾸지 않고 계산했어요.</p>
    </div>}
  </div>;
}
