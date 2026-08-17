"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const NAV_ITEMS = [
  { href: "/uebersicht", label: "Übersicht" },
  { href: "/kampagnen", label: "Kampagnen" },
  { href: "/kontakte", label: "Kontakte" },
  { href: "/live-anrufe", label: "Live-Anrufe" },
  { href: "/anrufhistorie", label: "Anrufhistorie" },
  { href: "/rueckrufe", label: "Rückrufe" },
  { href: "/dario", label: "Dario" },
  { href: "/prompt", label: "Prompt" },
  { href: "/stimme", label: "Stimme" },
  { href: "/telefonie", label: "Telefonie" },
  { href: "/sperrliste", label: "Sperrliste" },
  { href: "/einstellungen", label: "Einstellungen" },
];

export function NavSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-1 p-3">
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname?.startsWith(item.href + "/");
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            className={cn(
              "rounded-dv-sm px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-dv-accent-soft text-dv-accent"
                : "text-dv-text-secondary hover:bg-dv-surface-secondary hover:text-dv-text-primary"
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
