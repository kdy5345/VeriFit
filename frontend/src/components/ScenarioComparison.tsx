import { useEffect, useRef, useState } from "react";
import type { ScenarioResponse, UserProfile } from "../types/agent";
import { compareScenarios } from "../lib/api";
import { Card } from "./ui/Card";
import { Button } from "./ui/Button";
import { Field, Input, Select } from "./ui/Field";

const money = new Intl.NumberFormat("ko-KR");

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

  return <Card className="mt-6">
    <h3 className="m-0 text-body">조건을 바꾸면 얼마나 달라질까요?</h3>
    <p className="mt-2 text-callout text-content-assistive">현재 결과는 유지하고, 변경한 가정을 나란히 비교합니다.</p>
    <form onSubmit={(event) => {event.preventDefault(); void compare();}} className="grid gap-3 sm:grid-cols-3">
      <Field label="월 납입액 (원)"><Input type="number" disabled={loading} min="1" step="1" value={amount} onChange={(e) => {setAmount(e.target.value); setResult(null);}} /></Field>
      <Field label="기간 (개월)"><Input type="number" disabled={loading} min="1" max="60" step="1" value={term} onChange={(e) => {setTerm(e.target.value); setResult(null);}} /></Field>
      <Field label="급여이체 가정"><Select value={salary} disabled={loading} onChange={(e) => {setSalary(e.target.value); setResult(null);}}><option value="unchanged">현재 조건 유지</option><option value="yes">가능하다고 가정</option><option value="no">불가능하다고 가정</option></Select></Field>
      <div className="sm:col-span-3"><Button type="submit" disabled={loading}>{loading ? "재계산 중…" : "가정 비교하기"}</Button></div>
    </form>
    {error && <p role="alert" className="text-callout text-danger">{error}</p>}
    {result && <div className="mt-5 overflow-x-auto" aria-live="polite">
      <table className="w-full text-left text-callout"><caption className="mb-3 text-left font-bold">세후 이자 비교 · 월 {money.format(Number(amount))}원 / {term}개월</caption>
        <thead><tr><th className="py-2">상품</th><th>기존 → 변경 순위</th><th>변경 세후 이자</th><th>차이</th></tr></thead>
        <tbody>{result.scenarios[0].evaluation.results.map((product) => {
          const delta = result.scenarios[0].deltas.find((d) => d.product_key === product.product_key);
          return <tr key={product.product_key} className="border-t border-border-divider"><td className="py-3 pr-3">{product.institution_name} {product.product_name}<small className="block text-content-assistive">{product.reserve_type === "free" ? "자유적립" : "정액적립"} · {product.term_months}개월</small>{product.eligibility_status === "unknown" && <small className="block text-content-assistive">자격 확인 필요</small>}</td><td>{delta?.baseline_rank ?? "신규"} → {delta?.scenario_rank}</td><td>{money.format(product.after_tax_interest_won)}원</td><td>{delta?.after_tax_interest_delta_won == null ? "비교 기준 없음" : `${delta.after_tax_interest_delta_won > 0 ? "+" : ""}${money.format(delta.after_tax_interest_delta_won)}원`}</td></tr>;
        })}</tbody>
      </table>
      {result.scenarios[0].evaluation.results.length === 0 && <p>변경한 조건에 맞는 상품이 없습니다.</p>}
      {result.scenarios[0].evaluation.excluded_results.map((product) => <p key={product.product_key} className="text-footnote text-content-assistive">비교 제외: {product.product_name} — {product.eligibility_reasons.join(" · ")}</p>)}
      <p className="text-footnote leading-5 text-content-assistive">{result.disclaimer} 미확인 세부 조건은 자동 충족으로 바꾸지 않습니다.</p>
    </div>}
  </Card>;
}
