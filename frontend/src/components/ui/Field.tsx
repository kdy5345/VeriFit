import { forwardRef, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

const control = "w-full rounded-md border border-border-outline bg-background-root px-3 py-2.5 text-callout text-content outline-none transition placeholder:text-content-assistive focus:border-brand focus:ring-3 focus:ring-brand-regular disabled:text-content-disabled";

interface FieldProps { label: string; required?: boolean; hint?: string; children: React.ReactNode; className?: string }
export function Field({ label, required, hint, children, className = "" }: FieldProps) {
  return <label className={`grid gap-1.5 text-footnote font-bold text-content-additive ${className}`}><span>{label} {required && <em className="not-italic text-danger">*</em>}</span>{children}{hint && <small className="font-normal text-content-assistive">{hint}</small>}</label>;
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className = "", ...props }, ref) => <input ref={ref} className={`${control} min-h-10 ${className}`} {...props} />);
Input.displayName = "Input";
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className = "", ...props }, ref) => <textarea ref={ref} className={`${control} resize-y leading-6 ${className}`} {...props} />);
Textarea.displayName = "Textarea";
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className = "", ...props }, ref) => <select ref={ref} className={`${control} min-h-10 ${className}`} {...props} />);
Select.displayName = "Select";
