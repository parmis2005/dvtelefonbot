import { cn } from "@/lib/cn";

type Tone = "neutral" | "accent" | "warm" | "danger" | "success" | "cyan";

const toneClasses: Record<Tone, string> = {
  neutral: "bg-dv-surface-secondary text-dv-text-secondary",
  accent: "bg-dv-accent-soft text-dv-accent",
  warm: "bg-dv-accent-warm-soft text-dv-accent-warm",
  danger: "bg-dv-danger-soft text-dv-danger",
  success: "bg-dv-success-soft text-dv-success",
  cyan: "bg-dv-accent-cyan-soft text-dv-accent-cyan",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-dv-pill px-2.5 py-1 text-xs font-medium",
        toneClasses[tone]
      )}
    >
      {children}
    </span>
  );
}
