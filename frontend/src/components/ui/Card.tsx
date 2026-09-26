import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

interface CardProps { children: ReactNode; className?: string }
export function Card({ children, className = "" }: CardProps) {
  return <section className={`rounded-lg border border-border-divider bg-background-root p-6 shadow-[0_2px_8px_rgba(29,33,51,.025)] ${className}`}>{children}</section>;
}

interface CardHeaderProps { icon: LucideIcon; title: string; description: string; action?: ReactNode }
export function CardHeader({ icon: Icon, title, description, action }: CardHeaderProps) {
  return <header className="mb-5 flex flex-wrap items-center gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-regular text-brand"><Icon size={17} /></span><div><h3 className="m-0 text-body font-bold">{title}</h3><p className="m-0 text-footnote text-content-assistive">{description}</p></div>{action && <div className="ml-auto">{action}</div>}</header>;
}
