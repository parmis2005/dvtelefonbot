import { InputHTMLAttributes, LabelHTMLAttributes, TextareaHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-10 w-full rounded-dv-sm border border-dv-border bg-dv-surface px-3 text-sm text-dv-text-primary placeholder:text-dv-text-muted focus:border-dv-accent focus:outline-none focus:ring-2 focus:ring-dv-accent-soft transition-colors",
        className ?? ""
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full rounded-dv-sm border border-dv-border bg-dv-surface px-3 py-2 text-sm text-dv-text-primary placeholder:text-dv-text-muted focus:border-dv-accent focus:outline-none focus:ring-2 focus:ring-dv-accent-soft transition-colors",
      className ?? ""
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("mb-1.5 block text-sm font-medium text-dv-text-secondary", className ?? "")}
      {...props}
    />
  );
}

export const Select = forwardRef<
  HTMLSelectElement,
  React.SelectHTMLAttributes<HTMLSelectElement>
>(({ className, children, ...props }, ref) => (
  <select
    ref={ref}
    className={cn(
      "h-10 w-full rounded-dv-sm border border-dv-border bg-dv-surface px-3 text-sm text-dv-text-primary focus:border-dv-accent focus:outline-none focus:ring-2 focus:ring-dv-accent-soft transition-colors",
      className ?? ""
    )}
    {...props}
  >
    {children}
  </select>
));
Select.displayName = "Select";
