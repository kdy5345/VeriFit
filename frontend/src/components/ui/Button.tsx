import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "tertiary" | "danger";

const variants: Record<Variant, string> = {
  primary: "bg-brand text-content-elevated hover:opacity-90 focus-visible:ring-brand",
  secondary: "bg-background-fill text-content-additive hover:bg-background-fill-strong focus-visible:ring-brand",
  tertiary: "border border-border-outline bg-background-root text-content-additive hover:bg-background-fill focus-visible:ring-brand",
  danger: "bg-danger-regular text-danger hover:opacity-80 focus-visible:ring-danger",
};

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: Variant; size?: "sm" | "md"; icon?: ReactNode }

export function Button({ variant = "primary", size = "md", icon, className = "", children, ...props }: Props) {
  return <button className={`inline-flex items-center justify-center gap-2 rounded-md border-0 font-bold transition hover:-translate-y-px focus-visible:outline-none focus-visible:ring-3 disabled:cursor-wait disabled:opacity-50 disabled:hover:translate-y-0 ${size === "sm" ? "min-h-8 px-3 text-footnote" : "min-h-10 px-4 text-callout"} ${variants[variant]} ${className}`} {...props}>{children}{icon}</button>;
}
