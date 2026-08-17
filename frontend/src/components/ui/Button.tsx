import { ButtonHTMLAttributes, forwardRef } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-dv-accent text-white hover:bg-dv-accent-hover shadow-dv-sm disabled:bg-dv-text-muted",
  secondary:
    "bg-dv-surface text-dv-text-primary border border-dv-border hover:bg-dv-surface-hover",
  ghost: "bg-transparent text-dv-text-secondary hover:bg-dv-surface-secondary",
  danger: "bg-dv-danger text-white hover:opacity-90",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-8 px-3 text-sm rounded-dv-sm",
  md: "h-10 px-4 text-sm rounded-dv-md",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", size = "md", ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          "inline-flex items-center justify-center gap-2 font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60",
          variantClasses[variant],
          sizeClasses[size],
          className ?? ""
        )}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";
