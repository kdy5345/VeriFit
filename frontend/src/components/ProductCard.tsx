import { AlertCircle, ArrowUpRight, Check, FileSearch, Minus } from "lucide-react";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import type { ProductResult } from "../types/agent";

interface Props {
  product: ProductResult;
  rank: number;
  onOpenEvidence: (product: ProductResult) => void;
}

const won = new Intl.NumberFormat("ko-KR");

export function ProductCard({ product, rank, onOpenEvidence }: Props) {
  const applied = product.bonuses.filter((bonus) => bonus.satisfied);
  const unmet = product.bonuses.filter((bonus) => !bonus.satisfied);
  const range = Math.max(product.max_rate_bps - product.base_rate_bps, 1);
  const achievedPosition = Math.min(100, Math.max(0, ((product.achieved_rate_bps - product.base_rate_bps) / range) * 100));

  return (
    <Card className={`group relative overflow-hidden p-0 transition duration-200 hover:-translate-y-0.5 hover:border-brand/30 hover:shadow-[0_14px_36px_rgba(29,33,51,.08)] ${rank === 1 ? "border-brand/40" : ""}`}>
      {rank === 1 && <div className="absolute inset-x-0 top-0 h-1 bg-brand" />}
      <div className="p-5 sm:p-6">
        <header className="flex flex-wrap items-start gap-3 sm:gap-4">
          <span className={`grid size-10 shrink-0 place-items-center rounded-lg text-callout font-bold ${rank === 1 ? "bg-brand text-content-elevated" : "bg-background-fill text-content-assistive"}`}>
            {String(rank).padStart(2, "0")}
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-footnote font-bold text-brand">{product.institution_name}</span>
              <Badge label={product.reserve_type === "free" ? "자유적립" : "정액적립"} />
              {product.eligibility_warning && <Badge theme="status" label="자격 확인 필요" icon={<AlertCircle size={10} />} />}
            </div>
            <h3 className="mb-0 mt-1 break-words text-subhead leading-7">{product.product_name}</h3>
          </div>
          <div className="w-full border-t border-border-divider pt-3 text-left sm:w-auto sm:border-0 sm:pt-0 sm:text-right">
            <p className="m-0 text-footnote text-content-assistive">예상 적용금리</p>
            <strong className="mt-0.5 block font-inter text-[28px] leading-9 tracking-[-.03em] text-brand">
              {(product.achieved_rate_bps / 100).toFixed(2)}<small className="ml-0.5 text-callout">%</small>
            </strong>
          </div>
        </header>

        <div className="mt-6 rounded-lg bg-background-strong px-4 py-4">
          <div className="relative h-2 rounded-full bg-background-fill-strong">
            <div className="absolute inset-y-0 left-0 rounded-full bg-brand" style={{ width: `${Math.max(4, achievedPosition)}%` }} />
            <span className="absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-background-root bg-brand shadow-sm" style={{ left: `${Math.max(4, achievedPosition)}%` }} />
          </div>
          <div className="mt-3 flex justify-between text-caption text-content-assistive">
            <span>기본 {(product.base_rate_bps / 100).toFixed(2)}%</span>
            <span>최고 {(product.max_rate_bps / 100).toFixed(2)}%</span>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 divide-x divide-border-divider rounded-lg border border-border-divider py-3">
          <div className="px-4">
            <p className="m-0 text-footnote text-content-assistive">예상 세후 이자</p>
            <strong className="mt-1 block text-body">{won.format(product.after_tax_interest_won)}원</strong>
          </div>
          <div className="px-4">
            <p className="m-0 text-footnote text-content-assistive">만기 예상액</p>
            <strong className="mt-1 block text-body">{won.format(product.maturity_amount_won)}원</strong>
          </div>
        </div>

        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <div>
            <p className="mb-2 mt-0 text-footnote font-bold text-content-assistive">반영된 우대</p>
            <div className="space-y-2">
              {applied.length > 0 ? applied.slice(0, 2).map((bonus) => (
                <div key={bonus.bonus_id} className="flex items-center gap-2 text-callout">
                  <Check size={14} className="shrink-0 text-success" />
                  <span className="min-w-0 flex-1 truncate">{bonus.label}</span>
                  <strong className="shrink-0 text-success">+{(bonus.rate_bps / 100).toFixed(2)}%p</strong>
                </div>
              )) : <span className="text-callout text-content-assistive">기본금리 적용</span>}
            </div>
          </div>
          <div>
            <p className="mb-2 mt-0 text-footnote font-bold text-content-assistive">미반영 우대</p>
            <div className="space-y-2">
              {unmet.length > 0 ? unmet.slice(0, 2).map((bonus) => (
                <div key={bonus.bonus_id} className="flex items-center gap-2 text-callout text-content-assistive">
                  <Minus size={14} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate">{bonus.label}</span>
                  <span className="shrink-0">+{(bonus.rate_bps / 100).toFixed(2)}%p</span>
                </div>
              )) : <span className="text-callout text-content-assistive">추가 조건 없음</span>}
            </div>
          </div>
        </div>
      </div>

      <footer className="flex items-center justify-between border-t border-border-divider bg-background-strong/60 px-5 py-3 sm:px-6">
        <span className="text-footnote text-content-assistive">{product.term_months}개월 기준</span>
        <Button variant="secondary" size="sm" onClick={() => onOpenEvidence(product)} icon={<ArrowUpRight size={14} />}>
          <FileSearch size={14} /> 계산 근거
        </Button>
      </footer>
    </Card>
  );
}
