interface Option<T extends string> { label: string; value: T }
interface Props<T extends string> { value: T; onChange: (value: T) => void; options: Option<T>[] }
export function SegmentedControl<T extends string>({ value, onChange, options }: Props<T>) {
  return <div className="grid w-full max-w-xs grid-cols-2 rounded-lg bg-background-strong p-1" role="radiogroup">{options.map((option) => <button type="button" role="radio" aria-checked={value === option.value} key={option.value} onClick={() => onChange(option.value)} className={`min-h-9 rounded-md border-0 text-footnote font-bold transition ${value === option.value ? "bg-background-root text-content shadow-sm" : "bg-transparent text-content-assistive"}`}>{option.label}</button>)}</div>;
}
