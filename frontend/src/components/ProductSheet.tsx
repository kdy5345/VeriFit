import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import type { BonusResult, ProductResult } from "../types/agent";
import { formatRate, formatWon, reserveLabel } from "../lib/format";
import { BankMark } from "./ProductRow";

interface Props {
  product: ProductResult | null;
  onClose: () => void;
}

function bonusVerdict(bonus: BonusResult): { label: string; tone: string; detail: string } {
  if (bonus.satisfied) return { label: "반영", tone: "bg-success-regular text-success", detail: "입력한 조건과 맞아서 금리에 넣었어요. 우대 합산 한도가 있으면 한도까지만 더해요." };
  if (bonus.exclusion_reason) return { label: "중복 불가", tone: "bg-background-fill-strong text-content-additive", detail: `조건은 맞지만 ${bonus.exclusion_reason}이라 금리가 더 높은 쪽만 넣었어요.` };
  if (bonus.status === "unknown") return { label: "미확인", tone: "bg-warning-regular text-content-additive", detail: "판정에 필요한 정보가 부족해 현재 금리에는 넣지 않았어요." };
  return { label: "미충족", tone: "bg-background-fill-strong text-content-assistive", detail: "입력한 조건이 공시 기준에 못 미쳐요." };
}

function BonusItem({ bonus }: { bonus: BonusResult }) {
  const verdict = bonusVerdict(bonus);
  return <li className="py-4">
    <div className="flex items-center gap-2">
      <span className={`shrink-0 rounded-md px-1.5 py-0.5 text-footnote font-bold ${verdict.tone}`}>{verdict.label}</span>
      <strong className="min-w-0 flex-1 text-callout">{bonus.label}</strong>
      <span className={`shrink-0 text-callout font-bold tabular-nums ${bonus.satisfied ? "text-success" : "text-content-assistive"}`}>+{formatRate(bonus.rate_bps)}%p</span>
    </div>
    <blockquote className="mx-0 mb-0 mt-2.5 rounded-xl bg-background-fill px-3.5 py-3 text-callout leading-6 text-content-additive">{bonus.evidence_quote}</blockquote>
    <p className="mb-0 mt-2 text-footnote leading-5 text-content-assistive">{verdict.detail}</p>
  </li>;
}

function RateTrack({ product }: { product: ProductResult }) {
  const span = Math.max(product.max_rate_bps - product.base_rate_bps, 1);
  const position = (bps: number) => Math.min(100, Math.max(0, ((bps - product.base_rate_bps) / span) * 100));
  const achieved = position(product.achieved_rate_bps);
  const potential = position(product.potential_rate_bps);
  return <div>
    <div className="relative h-2.5 rounded-full bg-background-fill-strong">
      {potential > achieved && <div className="absolute inset-y-0 left-0 rounded-full bg-brand/25" style={{ width: `${potential}%` }} />}
      <div className="absolute inset-y-0 left-0 rounded-full bg-brand" style={{ width: `${Math.max(achieved, 2)}%` }} />
    </div>
    <div className="mt-2 flex justify-between text-footnote text-content-assistive tabular-nums">
      <span>기본 {formatRate(product.base_rate_bps)}%</span>
      <span>공시 최고 {formatRate(product.max_rate_bps)}%</span>
    </div>
  </div>;
}

export function ProductSheet({ product, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!product) return;
    closeRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [product]);
  if (!product) return null;

  const hasPotential = product.potential_rate_bps > product.achieved_rate_bps;
  return <div className="fixed inset-0 z-50 flex items-end justify-center bg-[rgba(17,18,20,.42)] sm:items-center sm:p-6" onMouseDown={onClose}>
    <div role="dialog" aria-modal="true" aria-label={`${product.product_name} 계산 근거`} onMouseDown={(event) => event.stopPropagation()}
      className="animate-sheet-up flex max-h-[88vh] w-full max-w-[560px] flex-col overflow-hidden rounded-t-[28px] bg-background-root sm:rounded-[28px]">
      <div className="flex items-start gap-3 px-6 pb-2 pt-6">
        <BankMark name={product.institution_name} size="lg" />
        <div className="min-w-0 flex-1">
          <p className="m-0 flex flex-wrap gap-x-2 text-footnote text-content-assistive"><span>{product.institution_name}</span><span>{reserveLabel(product.reserve_type)}</span><span>{product.term_months}개월</span></p>
          <h2 className="mb-0 mt-0.5 text-headline font-bold">{product.product_name}</h2>
        </div>
        <button ref={closeRef} type="button" aria-label="닫기" onClick={onClose} className="grid size-10 shrink-0 place-items-center rounded-full border-0 bg-background-fill text-content-additive hover:bg-background-fill-strong"><X size={18} /></button>
      </div>

      <div className="overflow-y-auto px-6 pb-8">
        <section className="pt-4">
          <p className="m-0 text-callout text-content-assistive">{product.term_months}개월 뒤 세후 이자</p>
          <p className="m-0 mt-1 text-[34px] font-extrabold leading-tight tracking-[-.03em] tabular-nums">{formatWon(product.after_tax_interest_won)}원</p>
          <p className="m-0 mt-1 text-callout text-content-assistive tabular-nums">만기에 {formatWon(product.maturity_amount_won)}원을 받아요</p>
        </section>

        <section className="mt-6 rounded-2xl bg-background-strong p-4">
          <div className="mb-3 flex items-baseline justify-between">
            <span className="text-callout font-bold">내 금리</span>
            <span className="text-headline font-extrabold text-brand tabular-nums">연 {formatRate(product.achieved_rate_bps)}%</span>
          </div>
          <RateTrack product={product} />
          {hasPotential && <p className="mb-0 mt-3 text-footnote leading-5 text-content-additive">미확인 우대를 모두 충족하면 연 {formatRate(product.potential_rate_bps)}%, 세후 {formatWon(product.potential_after_tax_interest_won)}원까지 가능해요. 아직 확정된 금리는 아니에요.</p>}
        </section>

        {product.eligibility_reasons.length > 0 && <section className="mt-4 rounded-2xl bg-danger-regular px-4 py-3">
          <p className="m-0 text-callout font-bold text-danger">가입 전에 확인하세요</p>
          <ul className="mb-0 mt-1.5 list-none space-y-1 p-0 text-footnote leading-5 text-content-additive">{product.eligibility_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
        </section>}

        <section className="mt-7">
          <h3 className="m-0 text-body font-bold">우대조건 {product.bonuses.length}개</h3>
          {product.bonuses.length > 0
            ? <ul className="m-0 list-none divide-y divide-border-divider p-0">{product.bonuses.map((bonus) => <BonusItem key={bonus.bonus_id} bonus={bonus} />)}</ul>
            : <p className="mb-0 mt-2 text-callout text-content-assistive">우대조건 없이 기본금리가 적용돼요.</p>}
        </section>

        <p className="mb-0 mt-4 text-footnote leading-5 text-content-assistive">
          공시월 {product.disclosed_month || "미확인"}, 검증 저장 {product.updated_at ? new Date(product.updated_at).toLocaleDateString("ko-KR") : "미확인"}<br />
          원문 버전: {product.source_hash?.slice(0, 12) || "미확인"}
        </p>
      </div>
    </div>
  </div>;
}
