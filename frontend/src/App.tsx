import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowRight, Check, ChevronDown, CircleHelp, MessageCircle, Moon, Plus, ShieldCheck, Sparkles, Sun, Wallet } from "lucide-react";
import { EvidenceDrawer } from "./components/EvidenceDrawer";
import { ProductCard } from "./components/ProductCard";
import { Badge } from "./components/ui/Badge";
import { Button } from "./components/ui/Button";
import { Card } from "./components/ui/Card";
import { SegmentedControl } from "./components/ui/SegmentedControl";
import { Textarea } from "./components/ui/Field";
import { setTheme, type ThemeName } from "./design-system";
import { askAgent } from "./lib/api";
import type { AskResponse, ProductResult } from "./types/agent";

type Screen = "start" | "loading" | "question" | "results" | "error";
type SortOrder = "rate" | "interest";
const money = new Intl.NumberFormat("ko-KR");
const examples = ["월 30만 원씩 1년, 급여이체는 가능해요", "월 50만 원씩 2년, 카드는 잘 안 써요", "복잡한 우대조건은 피하고 싶어요"];
const factNames: Record<string, string> = {
  salary_transfer: "급여이체", pension_transfer: "연금이체", utility_autopay: "공과금 자동이체",
  card_usage_amount: "카드 사용", auto_deposit_this_product: "적금 자동이체", first_time_customer: "첫 거래",
  open_banking_linked: "오픈뱅킹", consecutive_deposit: "연속 납입", online_channel_join: "비대면 가입",
  marketing_consent_sms: "문자 수신 동의", marketing_consent_call: "전화 수신 동의", other: "기타 조건",
};

function Composer({ value, onChange, onSubmit, compact = false, placeholder }: {
  value: string; onChange: (value: string) => void; onSubmit: () => void; compact?: boolean; placeholder: string;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (value.trim()) onSubmit();
    }
  }
  return <form onSubmit={(event: FormEvent) => { event.preventDefault(); if (value.trim()) onSubmit(); }} className="rounded-xl border border-border-outline bg-background-root p-3 shadow-[0_14px_45px_rgba(29,33,51,.07)] transition focus-within:border-brand focus-within:shadow-[0_16px_48px_rgba(53,103,243,.12)]">
    <Textarea value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={onKeyDown} rows={compact ? 2 : 4} maxLength={2000} aria-label="적금 조건 입력" placeholder={placeholder} className="min-h-24 resize-none border-0 bg-transparent px-2 py-2 text-body leading-7 shadow-none focus:border-0 focus:ring-0" />
    <div className="flex items-center justify-between gap-3 px-1 pt-1">
      <span className="text-footnote text-content-assistive">Enter로 보내기 · Shift+Enter로 줄바꿈</span>
      <Button type="submit" disabled={!value.trim()} icon={<ArrowRight size={16} />}>{compact ? "다시 계산" : "내 조건 분석하기"}</Button>
    </div>
  </form>;
}

function Intro({ input, setInput, submit }: { input: string; setInput: (value: string) => void; submit: () => void }) {
  return <section className="relative overflow-hidden px-5 pb-24 pt-16 text-center sm:px-8 sm:pt-24">
    <div className="pointer-events-none absolute inset-x-0 top-0 h-[530px] bg-[radial-gradient(ellipse_65%_65%_at_50%_20%,rgba(53,103,243,.13),transparent_78%)]" />
    <div className="relative mx-auto max-w-[900px]">
      <Badge theme="brand" size="large" label="나의 조건으로 다시 보는 적금" icon={<Sparkles size={12} />} />
      <h1 className="mx-auto mb-0 mt-6 max-w-[780px] text-[36px] font-bold leading-[1.26] tracking-[-.05em] sm:text-[54px]">보이는 최고금리보다<br /><span className="text-brand">내가 받을 금리</span>가 중요하니까</h1>
      <p className="mx-auto mb-0 mt-5 max-w-[620px] text-body leading-7 text-content-assistive sm:text-subhead sm:leading-8">매달 얼마를 넣을지, 어떤 조건이 가능한지만 말해주세요. 상품별 예상금리와 세후 이자를 계산하고 근거까지 보여드려요.</p>
      <div className="mx-auto mt-10 max-w-[740px] text-left"><Composer value={input} onChange={setInput} onSubmit={submit} placeholder="예: 월 30만 원씩 1년 넣고 싶어요. 급여이체는 가능하지만 카드는 잘 안 써요." /></div>
      <div className="mt-4 flex flex-wrap justify-center gap-2" aria-label="입력 예시">{examples.map((example) => <button key={example} type="button" onClick={() => setInput(example)} className="rounded-full border border-border-divider bg-background-root px-3.5 py-2 text-footnote text-content-additive transition hover:border-brand/40 hover:text-brand">{example}</button>)}</div>
      <div className="mx-auto mt-16 grid max-w-[740px] gap-3 text-left sm:grid-cols-3">
        {[[MessageCircle, "편하게 말해요", "평소 금융 습관을 자연어로 입력"], [Wallet, "내 금리로 비교해요", "충족 가능한 우대만 반영해 계산"], [ShieldCheck, "근거를 확인해요", "우대조건별 공시 문장까지 연결"]].map(([Icon, title, detail]) => {
          const FeatureIcon = Icon as typeof MessageCircle;
          return <div key={String(title)} className="rounded-xl border border-border-divider bg-background-interactive p-5 backdrop-blur-sm"><span className="grid size-9 place-items-center rounded-lg bg-brand-regular text-brand"><FeatureIcon size={17} /></span><strong className="mt-4 block text-callout">{String(title)}</strong><span className="mt-1 block text-footnote leading-5 text-content-assistive">{String(detail)}</span></div>;
        })}
      </div>
    </div>
  </section>;
}

function FactChips({ result }: { result: AskResponse }) {
  const profile = result.extracted_profile;
  if (!profile) return null;
  const chips = [
    { key: "amount", label: `월 ${money.format(profile.monthly_deposit_won)}원`, satisfied: true },
    { key: "term", label: `${profile.term_months}개월`, satisfied: true },
    ...Object.entries(profile.facts).map(([key, fact]) => ({ key, label: factNames[key] ?? key, satisfied: fact.satisfied })),
  ];
  return <div className="flex flex-wrap gap-2">{chips.map((chip) => <span key={chip.key} className={`inline-flex min-h-8 items-center gap-1.5 rounded-full px-3 py-1 text-footnote font-bold ${chip.satisfied ? "bg-brand-regular text-brand" : "bg-background-fill text-content-assistive"}`}>{chip.satisfied ? <Check size={13} /> : <span aria-hidden="true">−</span>}{chip.label}{!chip.satisfied && " 안 함"}</span>)}</div>;
}

export default function App() {
  const [theme, setCurrentTheme] = useState<ThemeName>("light");
  const [screen, setScreen] = useState<Screen>("start");
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortOrder>("rate");
  const [evidenceProduct, setEvidenceProduct] = useState<ProductResult | null>(null);
  const [showAll, setShowAll] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => {
    if (!evidenceProduct) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") setEvidenceProduct(null); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [evidenceProduct]);
  const sortedProducts = useMemo(() => [...(result?.products ?? [])].sort((a, b) => sort === "rate" ? b.achieved_rate_bps - a.achieved_rate_bps || b.after_tax_interest_won - a.after_tax_interest_won : b.after_tax_interest_won - a.after_tax_interest_won || b.achieved_rate_bps - a.achieved_rate_bps), [result, sort]);
  const visibleProducts = showAll ? sortedProducts : sortedProducts.slice(0, 5);

  async function submit() {
    const message = input.trim();
    if (!message || screen === "loading") return;
    const controller = new AbortController();
    requestRef.current = controller;
    setScreen("loading");
    setError("");
    try {
      const response = await askAgent(message, threadId, controller.signal);
      if (controller.signal.aborted) return;
      setResult(response);
      setThreadId(response.thread_id);
      setInput("");
      setSort("rate");
      setShowAll(false);
      setScreen(response.status === "needs_input" ? "question" : response.status === "failed" ? "error" : "results");
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "요청을 완료하지 못했습니다.");
      setScreen("error");
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }
  function reset() {
    requestRef.current?.abort();
    requestRef.current = null;
    setScreen("start"); setInput(""); setThreadId(null); setResult(null); setError(""); setSort("rate"); setShowAll(false); setEvidenceProduct(null);
  }
  function toggleTheme() {
    const next: ThemeName = theme === "light" ? "dark" : "light";
    setCurrentTheme(next); setTheme(next);
  }
  return <div className="min-h-screen bg-background-strong text-content">
    <header className="sticky top-0 z-30 border-b border-border-divider bg-background-interactive backdrop-blur-xl"><div className="mx-auto flex h-16 max-w-[1180px] items-center justify-between gap-4 px-5 sm:px-8">
      <button type="button" onClick={reset} aria-label="VeriFit 처음으로" className="flex items-center gap-2.5 border-0 bg-transparent p-0 text-content"><span className="grid size-9 place-items-center rounded-[10px] bg-brand text-content-elevated"><ShieldCheck size={19} /></span><span className="font-inter text-[19px] font-bold tracking-[-.045em]">VeriFit</span></button>
      <div className="flex items-center gap-2">{screen !== "start" && <Button variant="tertiary" size="sm" onClick={reset}><Plus size={14} /> 새 비교</Button>}<button type="button" onClick={toggleTheme} aria-label={theme === "light" ? "다크 모드 켜기" : "라이트 모드 켜기"} className="grid size-9 place-items-center rounded-md border border-border-divider bg-background-root text-content-additive">{theme === "light" ? <Moon size={16} /> : <Sun size={16} />}</button></div>
    </div></header>
    <main>
      {screen === "start" && <Intro input={input} setInput={setInput} submit={submit} />}
      {screen === "loading" && <section className="mx-auto max-w-[700px] px-5 py-20 sm:px-8 sm:py-28" role="status" aria-live="polite"><Card className="p-7 sm:p-9"><span className="grid size-12 place-items-center rounded-xl bg-brand text-content-elevated"><Sparkles size={22} className="animate-pulse" /></span><h1 className="mb-0 mt-5 text-title">조건을 분석하고 있어요</h1><p className="mb-0 mt-2 text-body leading-7 text-content-assistive">상품별 우대조건과 이자를 계산하고 답변을 확인하는 중입니다.</p><div className="mt-7 h-1.5 overflow-hidden rounded-full bg-brand-regular"><div className="h-full w-1/3 animate-[loading-slide_1.5s_ease-in-out_infinite] rounded-full bg-brand" /></div></Card></section>}
      {screen === "question" && result && <section className="mx-auto max-w-[760px] px-5 py-16 sm:px-8 sm:py-24"><div className="flex items-start gap-4"><span className="grid size-11 shrink-0 place-items-center rounded-xl bg-brand text-content-elevated"><CircleHelp size={21} /></span><div><p className="m-0 text-footnote font-bold text-brand">한 가지만 더 알려주세요</p><h1 className="mb-0 mt-1 text-title leading-9">{result.answer}</h1></div></div><div className="mt-8"><Composer value={input} onChange={setInput} onSubmit={submit} compact placeholder="빠진 정보만 답해도 돼요. 예: 매달 30만 원이야." /></div><p className="mt-3 text-center text-footnote text-content-assistive">앞서 말한 조건은 기억하고 있어요.</p></section>}
      {screen === "error" && <section className="mx-auto max-w-[700px] px-5 py-16 sm:px-8 sm:py-24"><Card className="p-7 sm:p-9"><h1 className="m-0 text-title">분석을 완료하지 못했어요</h1><p className="mb-0 mt-2 text-body leading-7 text-content-assistive">{error || result?.answer || "입력 내용을 확인하고 다시 시도해 주세요."}</p><div className="mt-6"><Composer value={input} onChange={setInput} onSubmit={submit} compact placeholder="조건을 다시 적어주세요." /></div><button type="button" onClick={reset} className="mt-4 border-0 bg-transparent text-footnote font-bold text-brand">처음부터 시작하기</button></Card></section>}
      {screen === "results" && result && <div className="mx-auto max-w-[1180px] px-5 py-10 sm:px-8 sm:py-14">
        <section className="rounded-xl border border-border-divider bg-background-root px-6 py-6 shadow-[0_10px_35px_rgba(29,33,51,.04)] sm:px-8 sm:py-7">
          <div className="flex items-center gap-2 text-footnote font-bold text-brand"><span className="grid size-7 place-items-center rounded-md bg-brand-regular"><Sparkles size={15} /></span> VeriFit 분석 결과</div>
          <h1 className="mb-0 mt-4 text-title leading-tight">내 조건으로 비교한 적금 <span className="text-brand">{result.products.length}개</span></h1>
          <p className="mb-0 mt-2 text-callout leading-6 text-content-assistive">예상금리와 세후 이자를 확인하고, 상품 카드에서 우대조건의 근거를 살펴보세요.</p>
          {result.answer && <details className="group mt-5 border-t border-border-divider pt-4"><summary className="flex cursor-pointer list-none items-center gap-2 text-callout font-bold text-content-additive marker:hidden hover:text-brand [&::-webkit-details-marker]:hidden">분석 설명 펼쳐보기 <ChevronDown size={16} className="transition-transform group-open:rotate-180" /></summary><p className="mb-0 mt-4 whitespace-pre-line text-callout leading-7 text-content-additive">{result.answer}</p></details>}
        </section>
        <div className="mt-8 grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
          <section className="min-w-0"><div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="m-0 text-footnote font-bold text-brand">내 조건으로 계산한 결과</p><h2 className="mb-0 mt-1 text-title">상품 비교 <span className="text-content-assistive">{sortedProducts.length}</span></h2></div>{sortedProducts.length > 1 && <SegmentedControl value={sort} onChange={(value) => { setSort(value); setShowAll(false); }} options={[{ label: "예상금리순", value: "rate" }, { label: "세후이자순", value: "interest" }]} />}</div>
            {visibleProducts.length > 0 ? <div className="space-y-4">{visibleProducts.map((product, index) => <ProductCard key={product.product_key} product={product} rank={index + 1} onOpenEvidence={setEvidenceProduct} />)}{sortedProducts.length > 5 && <button type="button" onClick={() => setShowAll(!showAll)} className="flex min-h-12 w-full items-center justify-center gap-2 rounded-lg border border-border-divider bg-background-root text-callout font-bold text-content-additive hover:border-brand/30 hover:text-brand">{showAll ? "상품 접기" : `나머지 ${sortedProducts.length - 5}개 상품 보기`} <ChevronDown size={16} className={showAll ? "rotate-180" : ""} /></button>}</div> : <Card className="p-8 text-center"><Wallet size={24} className="mx-auto text-content-assistive" /><p className="mb-0 mt-4 text-body font-bold">조건에 맞는 상품을 찾지 못했어요</p><p className="mb-0 mt-2 text-callout text-content-assistive">기간이나 조건을 바꿔 다시 계산해 보세요.</p></Card>}
          </section>
          <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start"><Card><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-brand-regular text-brand"><Check size={18} /></span><div><h3 className="m-0 text-body">인식한 조건</h3><p className="m-0 text-footnote text-content-assistive">이번 계산에 사용했어요</p></div></div><div className="mt-5"><FactChips result={result} /></div></Card>
            <Card><div className="flex items-center gap-3"><span className="grid size-9 place-items-center rounded-lg bg-success-regular text-success"><ShieldCheck size={17} /></span><div><h3 className="m-0 text-body">숫자와 근거 대조</h3><p className="m-0 text-footnote text-content-assistive">결과 생성 후 확인했어요</p></div></div><p className="mb-0 mt-4 text-callout leading-6 text-content-additive">금리와 이자는 코드로 계산하고, 상품별 우대조건은 공시 원문과 연결했어요.</p></Card>
            <Card className="border-brand/25"><div className="flex items-center gap-2 text-footnote font-bold text-brand"><MessageCircle size={16} /> 조건을 바꿔 다시 물어보세요</div><p className="mb-4 mt-2 text-callout leading-6 text-content-additive">기간이나 납입액만 바꿔 말해도 이전 대화에 이어 계산합니다.</p><Composer value={input} onChange={setInput} onSubmit={submit} compact placeholder="예: 월 50만 원으로 바꿔줘" /></Card>
          </aside>
        </div>
        <footer className="mt-10 flex items-start gap-2 border-t border-border-divider pt-5 text-footnote leading-5 text-content-assistive"><ShieldCheck size={14} className="mt-0.5 shrink-0" /><span>{result.disclaimer}</span></footer>
      </div>}
    </main>
    <EvidenceDrawer product={evidenceProduct} onClose={() => setEvidenceProduct(null)} />
  </div>;
}
