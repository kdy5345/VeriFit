import type { ReactNode } from "react";
import { Trash2 } from "lucide-react";

interface Props { title: string; onRemove: () => void; children: ReactNode }
export function EntryCard({ title, onRemove, children }: Props) {
  return <article className="rounded-lg border border-border-divider bg-background-strong/40 p-4"><div className="mb-4 flex items-center justify-between"><strong className="text-footnote text-brand">{title}</strong><button type="button" onClick={onRemove} className="flex items-center gap-1 border-0 bg-transparent text-caption text-content-assistive hover:text-danger"><Trash2 size={13} /> 삭제</button></div>{children}</article>;
}
