import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp, ChevronDown, Moon, Sun } from "lucide-react";
import { ProductRow } from "./components/ProductRow";
import { ProductSheet } from "./components/ProductSheet";
import { ScenarioComparison } from "./components/ScenarioComparison";
import { setTheme, type ThemeName } from "./design-system";
import { askAgent, restoreConversation } from "./lib/api";
import { formatRate, formatWon } from "./lib/format";
import type { AskResponse, ProductResult } from "./types/agent";

type Screen = "start" | "loading" | "question" | "results" | "error";
type SortOrder = "interest" | "rate";
const examples = ["월 30만 원씩 1년, 급여이체는 가능해요", "월 50만 원씩 2년, 카드는 잘 안 써요", "복잡한 우대조건은 피하고 싶어요"];
const factNames: Record<string, string> = {
  salary_transfer: "급여이체", pension_transfer: "연금이체", utility_autopay: "공과금 자동이체",
  card_usage_amount: "카드 사용", auto_deposit_this_product: "적금 자동이체", first_time_customer: "첫 거래",
  open_banking_linked: "오픈뱅킹", consecutive_deposit: "연속 납입", online_channel_join: "비대면 가입",
  marketing_consent_sms: "문자 수신 동의", marketing_consent_call: "전화 수신 동의", other: "기타 조건",
};

function submitOnEnter(event: KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>, value: string, onSubmit: () => void) {
  if (event.key !== "Enter" || event.shiftKey) return;
  event.preventDefault();
  if (!event.nativeEvent.isComposing && value.trim()) onSubmit();
}

function Composer({ value, onChange, onSubmit, placeholder, action }: {
  value: string; onChange: (value: string) => void; onSubmit: () => void; placeholder: string; action: string;
}) {
  return <form onSubmit={(event: FormEvent) => { event.preventDefault(); if (value.trim()) onSubmit(); }}>
    <textarea value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => submitOnEnter(event, value, onSubmit)} rows={4} maxLength={2000} aria-label="적금 조건 입력" placeholder={placeholder}
      className="block min-h-36 w-full resize-none rounded-[20px] border-0 bg-background-fill-strong px-5 py-4 text-subhead leading-7 text-content outline-none transition-shadow placeholder:text-content-disabled focus:shadow-[inset_0_0_0_2px_var(--brand)]" />
    <button type="submit" disabled={!value.trim()} className="mt-3 min-h-14 w-full rounded-[18px] border-0 bg-brand text-body font-bold text-content-elevated transition-[filter,opacity] hover:brightness-110 active:brightness-95 disabled:cursor-not-allowed disabled:opacity-35">{action}</button>
  </form>;
}

function FactChips({ result }: { result: AskResponse }) {
  const profile = result.extracted_profile;
  if (!profile) return null;
  const chips = [
    { key: "amount", label: `월 ${formatWon(profile.monthly_deposit_won)}원`, muted: false },
    { key: "term", label: `${profile.term_months}개월`, muted: false },
    ...Object.entries(profile.facts).map(([key, fact]) => ({
      key, muted: fact.satisfied !== true,
      label: `${factNames[key] ?? key}${fact.satisfied === null ? " 미확인" : fact.satisfied === false ? " 안 함" : " 가능"}`,
    })),
  ];
  return <ul aria-label="인식한 조건" className="m-0 flex list-none flex-wrap gap-1.5 p-0">{chips.map((chip) =>
    <li key={chip.key} className={`rounded-full px-3 py-1.5 text-footnote font-bold ${chip.muted ? "bg-background-fill-strong text-content-assistive" : "bg-background-root text-content-additive"}`}>{chip.label}</li>)}
  </ul>;
}

function Hero({ product, onOpen }: { product: ProductResult; onOpen: () => void }) {
  return <section className="rounded-[28px] bg-background-root px-6 pb-6 pt-7">
    <p className="m-0 text-callout font-bold text-content-assistive">세후 이자가 가장 많은 적금</p>
    <h1 className="mb-0 mt-2 text-headline font-bold leading-snug">{product.product_name}</h1>
    <p className="m-0 mt-0.5 text-callout text-content-assistive">{product.institution_name}{product.eligibility_warning && <span className="ml-2 font-bold text-danger">자격 확인 필요</span>}</p>
    <p className="m-0 mt-6 text-[40px] font-extrabold leading-none tracking-[-.035em] tabular-nums sm:text-[46px]">{formatWon(product.after_tax_interest_won)}원</p>
    <p className="m-0 mt-2 text-callout text-content-assistive">{product.term_months}개월 뒤 받는 세후 이자</p>
    <dl className="m-0 mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-2xl bg-border-divider">
      <div className="bg-background-strong px-4 py-3.5">
        <dt className="text-footnote text-content-assistive">공시 최고금리</dt>
        <dd className="m-0 mt-1 text-subhead font-bold text-content-disabled line-through decoration-2 tabular-nums">연 {formatRate(product.max_rate_bps)}%</dd>
      </div>
      <div className="bg-background-strong px-4 py-3.5">
        <dt className="text-footnote text-brand">내가 받을 금리</dt>
        <dd className="m-0 mt-1 text-subhead font-extrabold text-brand tabular-nums">연 {formatRate(product.achieved_rate_bps)}%</dd>
      </div>
    </dl>
    <button type="button" onClick={onOpen} className="mt-3 min-h-12 w-full rounded-2xl border-0 bg-brand-regular text-callout font-bold text-brand transition-colors hover:bg-brand/15">계산 근거 보기</button>
  </section>;
}

function Explanation({ result }: { result: AskResponse }) {
  const [open, setOpen] = useState(false);
  if (!result.answer) return null;
  return <section className="rounded-[24px] bg-background-root px-5 py-4">
    <p className={`m-0 whitespace-pre-line text-callout leading-6 text-content-additive ${open ? "" : "line-clamp-3"}`}>{result.answer}</p>
    <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="mt-2 border-0 bg-transparent p-0 text-footnote font-bold text-content-assistive hover:text-content">{open ? "접기" : "설명 더 보기"}</button>
    {result.used_fallback && result.products.length > 0 && <p className="mb-0 mt-2 text-footnote leading-5 text-content-assistive">AI가 쓴 설명이 숫자 검증을 통과하지 못해 계산 결과로 대신 보여드려요.</p>}
  </section>;
}

export default function App() {
  const [theme, setCurrentTheme] = useState<ThemeName>("light");
  const [screen, setScreen] = useState<Screen>("start");
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [error, setError] = useState("");
  const [sort, setSort] = useState<SortOrder>("interest");
  const [openProduct, setOpenProduct] = useState<ProductResult | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showScenario, setShowScenario] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const followUpRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const saved = sessionStorage.getItem("verifit.thread");
    if (!saved) return;
    const controller = new AbortController();
    requestRef.current = controller;
    setScreen("loading");
    restoreConversation(saved, controller.signal).then((response) => {
      if (controller.signal.aborted) return;
      setResult(response); setThreadId(response.thread_id);
      setScreen(response.status === "needs_input" ? "question" : response.status === "failed" ? "error" : "results");
    }).catch((caught) => {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? `대화 복원 실패: ${caught.message}` : "대화를 복원하지 못했습니다.");
      setScreen("error");
    });
    return () => controller.abort();
  }, []);
  useEffect(() => () => requestRef.current?.abort(), []);
  useEffect(() => {
    if (!openProduct) return;
    const closeOnEscape = (event: globalThis.KeyboardEvent) => { if (event.key === "Escape") setOpenProduct(null); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [openProduct]);

  const sortedProducts = useMemo(() => [...(result?.products ?? [])].sort((a, b) => sort === "rate"
    ? b.achieved_rate_bps - a.achieved_rate_bps || b.after_tax_interest_won - a.after_tax_interest_won
    : b.after_tax_interest_won - a.after_tax_interest_won || b.achieved_rate_bps - a.achieved_rate_bps), [result, sort]);
  const best = useMemo(() => [...(result?.products ?? [])].sort((a, b) => b.after_tax_interest_won - a.after_tax_interest_won)[0], [result]);
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
      sessionStorage.setItem("verifit.thread", response.thread_id);
      setInput("");
      setSort("interest");
      setShowAll(false);
      setScreen(response.status === "needs_input" ? "question" : response.status === "failed" ? "error" : "results");
      window.scrollTo({ top: 0 });
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(caught instanceof Error ? caught.message : "요청을 완료하지 못했습니다.");
      setScreen("error");
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
    }
  }
  function reset() {
    sessionStorage.removeItem("verifit.thread");
    requestRef.current?.abort();
    requestRef.current = null;
    setScreen("start"); setInput(""); setThreadId(null); setResult(null); setError(""); setSort("interest"); setShowAll(false); setShowScenario(false); setOpenProduct(null);
  }
  function toggleTheme() {
    const next: ThemeName = theme === "light" ? "dark" : "light";
    setCurrentTheme(next); setTheme(next);
  }

  const onResults = screen === "results" && result;
  return <div className={`min-h-screen text-content ${onResults ? "bg-background-strong" : "bg-background-root"}`}>
    <header className={`sticky top-0 z-30 backdrop-blur-xl ${onResults ? "bg-background-strong/85" : "bg-background-root/85"}`}>
      <div className="mx-auto flex h-14 max-w-[600px] items-center justify-between px-4 sm:px-6">
        <button type="button" onClick={reset} aria-label="VeriFit 처음으로" className="border-0 bg-transparent p-0 text-[19px] font-extrabold tracking-[-.04em] text-content">Veri<span className="text-brand">Fit</span></button>
        <div className="flex items-center gap-1">
          {screen !== "start" && <button type="button" onClick={reset} className="min-h-9 rounded-xl border-0 bg-transparent px-3 text-callout font-bold text-content-additive hover:bg-background-fill">새 비교</button>}
          <button type="button" onClick={toggleTheme} aria-label={theme === "light" ? "다크 모드 켜기" : "라이트 모드 켜기"} className="grid size-9 place-items-center rounded-xl border-0 bg-transparent text-content-assistive hover:bg-background-fill">{theme === "light" ? <Moon size={17} /> : <Sun size={17} />}</button>
        </div>
      </div>
    </header>

    <main className="mx-auto max-w-[600px] px-4 sm:px-6">
      {screen === "start" && <section className="pb-16 pt-10 sm:pt-16">
        <h1 className="m-0 text-[30px] font-extrabold leading-[1.3] tracking-[-.04em] sm:text-[36px]">광고 금리 말고<br />내가 받을 금리로<br />적금을 비교해요</h1>
        <p className="mb-0 mt-4 text-body leading-7 text-content-assistive">얼마를 몇 개월 넣을지, 어떤 조건이 가능한지 평소 말투로 적어주세요.</p>
        <div className="mt-8"><Composer value={input} onChange={setInput} onSubmit={submit} action="내 조건 분석하기" placeholder="월 30만 원씩 1년 넣고 싶어요. 급여이체는 되는데 카드는 잘 안 써요." /></div>
        <div className="mt-6">
          <p className="m-0 text-footnote font-bold text-content-assistive">이렇게 써도 돼요</p>
          <div className="mt-2 flex flex-wrap gap-2">{examples.map((example) => <button key={example} type="button" onClick={() => setInput(example)} className="rounded-full border-0 bg-background-fill-strong px-3.5 py-2 text-callout text-content-additive transition-colors hover:bg-background-fill hover:text-content">{example}</button>)}</div>
        </div>
      </section>}

      {screen === "loading" && <section className="pt-24" role="status" aria-live="polite">
        <div className="flex gap-1.5" aria-hidden="true">{[0, 1, 2].map((i) => <span key={i} className="size-2.5 animate-[dot_1.1s_ease-in-out_infinite] rounded-full bg-brand" style={{ animationDelay: `${i * 0.15}s` }} />)}</div>
        <h1 className="mb-0 mt-6 text-[26px] font-extrabold leading-[1.35] tracking-[-.035em]">조건에 맞는 적금을<br />계산하고 있어요</h1>
        <p className="mb-0 mt-3 text-body text-content-assistive">우대조건을 하나씩 대조하고 답변 숫자를 확인하는 중이에요.</p>
      </section>}

      {screen === "question" && result && <section className="pb-16 pt-12">
        <p className="m-0 text-callout font-bold text-brand">하나만 더 알려주세요</p>
        <h1 className="mb-0 mt-2 text-[26px] font-extrabold leading-[1.35] tracking-[-.035em]">{result.answer}</h1>
        <div className="mt-8"><Composer value={input} onChange={setInput} onSubmit={submit} action="보내기" placeholder="빠진 내용만 답해도 돼요. 예: 매달 30만 원이야." /></div>
        <p className="mb-0 mt-3 text-center text-footnote text-content-assistive">앞에서 말한 조건은 기억하고 있어요.</p>
      </section>}

      {screen === "error" && <section className="pb-16 pt-12">
        <h1 className="m-0 text-[26px] font-extrabold leading-[1.35] tracking-[-.035em]">분석을 마치지 못했어요</h1>
        <p className="mb-0 mt-3 text-body leading-7 text-content-assistive">{error || result?.answer || "입력 내용을 확인하고 다시 보내주세요."}</p>
        <div className="mt-8"><Composer value={input} onChange={setInput} onSubmit={submit} action="다시 보내기" placeholder="금액과 기간을 숫자와 단위로 적어주세요. 예: 월 30만 원, 12개월" /></div>
        <button type="button" onClick={reset} className="mt-4 w-full border-0 bg-transparent py-2 text-callout font-bold text-content-assistive hover:text-content">처음부터 다시 하기</button>
      </section>}

      {onResults && <div className="space-y-3 pb-36 pt-3">
        <FactChips result={result} />
        {best ? <Hero product={best} onOpen={() => setOpenProduct(best)} /> : <section className="rounded-[28px] bg-background-root px-6 py-10">
          <h1 className="m-0 text-headline font-bold">조건에 맞는 적금이 없어요</h1>
          <p className="mb-0 mt-2 text-callout leading-6 text-content-assistive">기간이나 납입액을 바꿔서 아래 입력창에 다시 말해 보세요.</p>
        </section>}
        <Explanation result={result} />

        {result.next_question && <section className="rounded-[24px] bg-brand-regular px-5 py-5">
          {result.next_question.interest_gain_won > 0 && <p className="m-0 text-callout font-bold text-brand tabular-nums">알려주시면 최대 {formatWon(result.next_question.interest_gain_won)}원 더 받을 수 있어요</p>}
          <p className="mb-0 mt-1.5 text-subhead font-bold leading-7">{result.next_question.question}</p>
          <p className="mb-0 mt-1.5 text-footnote leading-5 text-content-assistive">{result.next_question.explanation}</p>
          <button type="button" onClick={() => followUpRef.current?.focus()} className="mt-4 min-h-11 rounded-xl border-0 bg-brand px-4 text-callout font-bold text-content-elevated hover:brightness-110">답하기</button>
        </section>}

        {sortedProducts.length > 0 && <section className="rounded-[28px] bg-background-root px-3 pb-3 pt-5">
          <div className="flex items-center justify-between px-3 pb-2">
            <h2 className="m-0 text-body font-bold">전체 {sortedProducts.length}개</h2>
            <div role="radiogroup" aria-label="정렬" className="flex gap-1">
              {([["interest", "이자 많은 순"], ["rate", "금리 높은 순"]] as const).map(([value, label]) => <button key={value} type="button" role="radio" aria-checked={sort === value} onClick={() => { setSort(value); setShowAll(false); }} className={`rounded-lg border-0 px-2.5 py-1.5 text-footnote font-bold transition-colors ${sort === value ? "bg-background-fill-strong text-content" : "bg-transparent text-content-assistive hover:text-content"}`}>{label}</button>)}
            </div>
          </div>
          <ul className="m-0 list-none p-0">{visibleProducts.map((product) => <ProductRow key={product.product_key} product={product} onOpen={setOpenProduct} />)}</ul>
          {sortedProducts.length > 5 && <button type="button" onClick={() => setShowAll(!showAll)} aria-expanded={showAll} className="mt-1 flex min-h-12 w-full items-center justify-center gap-1 rounded-2xl border-0 bg-transparent text-callout font-bold text-content-assistive hover:bg-background-fill">{showAll ? "접기" : `${sortedProducts.length - 5}개 더 보기`}<ChevronDown size={16} className={showAll ? "rotate-180" : ""} /></button>}
        </section>}

        {result.extracted_profile && <section className="rounded-[28px] bg-background-root px-6 py-5">
          <button type="button" onClick={() => setShowScenario(!showScenario)} aria-expanded={showScenario} className="flex w-full items-center justify-between border-0 bg-transparent p-0 text-left">
            <span><span className="block text-body font-bold">조건 바꿔서 계산해보기</span><span className="mt-0.5 block text-footnote text-content-assistive">지금 결과는 그대로 두고 나란히 비교해요</span></span>
            <ChevronDown size={18} className={`shrink-0 text-content-assistive transition-transform ${showScenario ? "rotate-180" : ""}`} />
          </button>
          {showScenario && <div className="mt-5"><ScenarioComparison key={JSON.stringify(result.extracted_profile)} profile={result.extracted_profile} /></div>}
        </section>}

        {(result.excluded_products ?? []).length > 0 && <details className="group rounded-[24px] bg-background-root px-6 py-4">
          <summary className="flex cursor-pointer list-none items-center justify-between text-callout font-bold text-content-additive [&::-webkit-details-marker]:hidden">가입 조건이 안 맞아 뺀 상품 {result.excluded_products.length}개<ChevronDown size={16} className="text-content-assistive transition-transform group-open:rotate-180" /></summary>
          <ul className="mb-0 mt-3 list-none space-y-2 p-0">{result.excluded_products.map((p) => <li key={p.product_key} className="text-footnote leading-5 text-content-assistive"><strong className="text-content-additive">{p.institution_name} {p.product_name}</strong><br />{p.eligibility_reasons.join(", ")}</li>)}</ul>
        </details>}

        <p className="m-0 px-2 pt-2 text-footnote leading-5 text-content-assistive">{result.disclaimer}</p>
      </div>}
    </main>

    {onResults && <div className="fixed inset-x-0 bottom-0 z-40 bg-linear-to-t from-background-strong from-60% to-transparent px-4 pb-5 pt-8 sm:px-6">
      <form onSubmit={(event) => { event.preventDefault(); if (input.trim()) void submit(); }} className="mx-auto flex max-w-[552px] items-center gap-2 rounded-[22px] bg-background-root p-2 pl-5 shadow-[0_6px_24px_rgba(29,33,51,.10)]">
        <input ref={followUpRef} value={input} onChange={(event) => setInput(event.target.value)} onKeyDown={(event) => submitOnEnter(event, input, () => void submit())} maxLength={2000} aria-label="적금 조건 입력"
          placeholder={result.next_question ? "답하거나 조건을 바꿔 말해보세요" : "예: 2년으로 바꿔줘"} className="min-w-0 flex-1 border-0 bg-transparent py-2 text-body text-content outline-none placeholder:text-content-disabled" />
        <button type="submit" disabled={!input.trim()} aria-label="다시 계산" className="grid size-11 shrink-0 place-items-center rounded-2xl border-0 bg-brand text-content-elevated transition-opacity disabled:opacity-30"><ArrowUp size={20} /></button>
      </form>
    </div>}

    <ProductSheet product={openProduct} onClose={() => setOpenProduct(null)} />
  </div>;
}
