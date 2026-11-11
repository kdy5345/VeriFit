import { ChevronRight } from "lucide-react";
import type { ProductResult } from "../types/agent";
import { formatRate, formatWon, reserveLabel } from "../lib/format";

export function BankMark({ name, size = "md" }: { name: string; size?: "md" | "lg" }) {
  return <span aria-hidden="true" className={`grid shrink-0 place-items-center rounded-full bg-brand-regular font-extrabold text-brand ${size === "lg" ? "size-12 text-subhead" : "size-10 text-body"}`}>{name.slice(0, 1)}</span>;
}

export function ProductRow({ product, onOpen }: { product: ProductResult; onOpen: (product: ProductResult) => void }) {
  return <li>
    <button type="button" onClick={() => onOpen(product)} aria-label={`${product.institution_name} ${product.product_name} 자세히 보기`} className="flex w-full items-center gap-3.5 rounded-2xl border-0 bg-transparent px-3 py-3.5 text-left transition-colors hover:bg-background-fill active:bg-background-fill-strong">
      <BankMark name={product.institution_name} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-body font-bold text-content">{product.product_name}</span>
        <span className="mt-0.5 flex flex-wrap gap-x-2 text-footnote text-content-assistive">
          <span>{product.institution_name}</span>
          <span>{reserveLabel(product.reserve_type)}</span>
          {product.eligibility_warning && <span className="font-bold text-danger">자격 확인 필요</span>}
        </span>
      </span>
      <span className="shrink-0 text-right tabular-nums">
        <span className="block text-body font-bold text-content">{formatWon(product.after_tax_interest_won)}원</span>
        <span className="block text-footnote text-content-assistive">연 {formatRate(product.achieved_rate_bps)}%</span>
      </span>
      <ChevronRight size={18} className="shrink-0 text-content-disabled" aria-hidden="true" />
    </button>
  </li>;
}
