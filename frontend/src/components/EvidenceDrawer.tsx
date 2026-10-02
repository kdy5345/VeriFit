import { CheckCircle2, CircleHelp, X, XCircle } from "lucide-react";
import type { BonusResult, ProductResult } from "../types/agent";

interface Props {
  product: ProductResult | null;
  onClose: () => void;
}

function EvidenceRow({ bonus }: { bonus: BonusResult }) {
  const Icon = bonus.satisfied ? CheckCircle2 : bonus.status === "unknown" ? CircleHelp : XCircle;
  return (
    <article className="rounded-lg border border-border-divider bg-background-root p-4">
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-full ${bonus.satisfied ? "bg-success-regular text-success" : "bg-background-fill text-content-assistive"}`}>
          <Icon size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <strong className="text-callout">{bonus.label}</strong>
            <span className={bonus.satisfied ? "text-callout font-bold text-success" : "text-callout font-bold text-content-assistive"}>
              +{(bonus.rate_bps / 100).toFixed(2)}%p
            </span>
          </div>
          <p className="mb-0 mt-3 text-footnote font-bold text-content-assistive">공시 원문</p>
          <blockquote className="mb-0 mt-1 border-l-2 border-brand pl-3 text-callout leading-6 text-content-additive">
            “{bonus.evidence_quote}”
          </blockquote>
          <p className="mb-0 mt-3 text-footnote text-content-assistive">
            {bonus.satisfied ? "입력한 조건과 일치하는 우대예요. 실제 합산에는 우대 한도가 적용됩니다." : bonus.exclusion_reason ? `조건은 충족했지만 ${bonus.exclusion_reason} 때문에 제외됐어요.` : bonus.status === "unknown" ? "판정에 필요한 정보가 부족해 미확인 상태예요. 현재 금리에는 포함하지 않았어요." : "입력한 정보가 기준에 미달해 미충족으로 판정했어요."}
          </p>
        </div>
      </div>
    </article>
  );
}

export function EvidenceDrawer({ product, onClose }: Props) {
  if (!product) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-[rgba(17,18,20,.38)] backdrop-blur-[2px]" onMouseDown={onClose}>
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`${product.product_name} 계산 근거`}
        className="h-full w-full max-w-[520px] overflow-y-auto bg-background-strong shadow-[-20px_0_60px_rgba(29,33,51,.16)] animate-fade-up"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-border-divider bg-background-interactive px-6 py-5 backdrop-blur-xl">
          <div>
            <p className="m-0 text-footnote font-bold text-brand">금리 계산 근거</p>
            <h2 className="mb-0 mt-1 text-headline">{product.product_name}</h2>
          </div>
          <button type="button" aria-label="닫기" onClick={onClose} className="grid size-10 place-items-center rounded-full border-0 bg-background-fill text-content-additive hover:bg-background-fill-strong">
            <X size={19} />
          </button>
        </div>
        <div className="space-y-6 p-6">
          <p className="text-footnote leading-5 text-content-assistive">공시월: {product.disclosed_month || "미확인"} · 검증 저장 시각: {product.updated_at ? new Date(product.updated_at).toLocaleString("ko-KR") : "미확인"}<br />원문 버전: {product.source_hash?.slice(0, 12) || "미확인"}</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-brand-regular p-4">
              <p className="m-0 text-footnote text-content-assistive">예상 적용금리</p>
              <strong className="mt-1 block text-title text-brand">{(product.achieved_rate_bps / 100).toFixed(2)}%</strong>
            </div>
            <div className="rounded-lg bg-background-fill p-4">
              <p className="m-0 text-footnote text-content-assistive">공시 최고금리</p>
              <strong className="mt-1 block text-title">{(product.max_rate_bps / 100).toFixed(2)}%</strong>
            </div>
          </div>
          <section>
            <h3 className="mb-3 mt-0 text-body">우대조건별 판정</h3>
            <div className="space-y-3">
              {product.bonuses.length > 0 ? product.bonuses.map((bonus) => <EvidenceRow key={bonus.bonus_id} bonus={bonus} />) : (
                <p className="rounded-lg bg-background-fill p-4 text-callout text-content-assistive">별도의 우대조건 없이 기본금리가 적용되는 상품입니다.</p>
              )}
            </div>
          </section>
        </div>
      </aside>
    </div>
  );
}
