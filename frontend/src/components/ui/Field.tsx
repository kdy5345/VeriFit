import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const control = "w-full rounded-xl border-0 bg-background-fill-strong px-3.5 py-3 text-body text-content outline-none transition-shadow placeholder:text-content-disabled focus:shadow-[inset_0_0_0_2px_var(--brand)] disabled:text-content-disabled";

interface FieldProps { label: string; required?: boolean; hint?: string; children: React.ReactNode; className?: string }
export function Field({ label, required, hint, children, className = "" }: FieldProps) {
  return <label className={`grid gap-1.5 text-footnote font-bold text-content-additive ${className}`}><span>{label} {required && <em className="not-italic text-danger">*</em>}</span>{children}{hint && <small className="font-normal text-content-assistive">{hint}</small>}</label>;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className = "", ...props }, ref) => <input ref={ref} className={`${control} min-h-12 ${className}`} {...props} />);
Input.displayName = "Input";
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className = "", ...props }, ref) => <textarea ref={ref} className={`${control} resize-y leading-6 ${className}`} {...props} />);
Textarea.displayName = "Textarea";
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className = "", ...props }, ref) => <select ref={ref} className={`${control} min-h-12 ${className}`} {...props} />);
Select.displayName = "Select";
