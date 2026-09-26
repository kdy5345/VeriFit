import type { ReactNode } from "react";

type Variant = "normal" | "dot" | "count" | "icon";
type Theme = "neutral" | "brand" | "status";
type Size = "small" | "large";

const tint: Record<Theme, string> = {
  neutral: "bg-background-fill-strong text-content-additive",
  brand: "bg-brand-regular text-brand",
  status: "bg-danger-regular text-danger",
};

const solid: Record<Theme, string> = {
  neutral: "bg-background-fill-inverted text-content-inverted",
  brand: "bg-brand text-content-elevated",
  status: "bg-danger text-content-elevated",
};

interface Props { variant?: Variant; theme?: Theme; size?: Size; label?: string; icon?: ReactNode; className?: string }

export function Badge({ variant = "normal", theme = "neutral", size = "small", label, icon, className = "" }: Props) {
  if (variant === "dot") {
    return <i className={`inline-block shrink-0 rounded-full ${size === "large" ? "size-1.5" : "size-1"} ${solid[theme].split(" ")[0]} ${className}`} />;
  }
  if (variant === "count") {
    return <span className={`inline-flex shrink-0 items-center justify-center rounded-full font-bold leading-none ${size === "large" ? "h-[26px] min-w-[26px] px-1 text-footnote" : "h-[18px] min-w-[18px] px-0.5 text-caption"} ${solid[theme]} ${className}`}>{label}</span>;
  }
  if (variant === "icon") {
    return <span className={`inline-flex shrink-0 items-center justify-center rounded-full ${size === "large" ? "size-6 p-1" : "size-4 p-0.5"} ${solid[theme]} ${className}`}>{icon}</span>;
  }
  return <span className={`inline-flex shrink-0 items-center gap-1 rounded-sm font-bold leading-none ${size === "large" ? "px-1.5 py-1 text-footnote" : "px-1 py-0.5 text-caption"} ${tint[theme]} ${className}`}>{icon}{label}</span>;
}
