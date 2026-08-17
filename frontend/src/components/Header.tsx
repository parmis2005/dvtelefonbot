"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface HealthResponse {
  status: string;
  agent: string;
  company: string;
}

export function Header({ onMenuToggle }: { onMenuToggle?: () => void }) {
  const [online, setOnline] = useState<boolean | null>(null);
  const { logout } = useAuth();

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        await api.get<HealthResponse>("/api/health");
        if (!cancelled) setOnline(true);
      } catch {
        if (!cancelled) setOnline(false);
      }
    }
    check();
    const interval = setInterval(check, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <header className="flex h-16 items-center justify-between border-b border-dv-border-subtle bg-dv-surface px-4 md:px-6">
      <div className="flex items-center gap-3">
        <button
          onClick={onMenuToggle}
          className="rounded-dv-sm p-2 text-dv-text-secondary hover:bg-dv-surface-secondary md:hidden"
          aria-label="Menü"
        >
          ☰
        </button>
        <div>
          <div className="font-display text-base font-bold leading-tight text-dv-text-primary">
            DVTelefonbot
          </div>
          <div className="text-xs text-dv-text-muted">Digital Vision AI Calling System</div>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <span className="hidden items-center gap-1.5 text-xs font-medium text-dv-text-secondary sm:flex">
          <span
            className={`h-2 w-2 rounded-full ${
              online === null
                ? "bg-dv-text-muted"
                : online
                  ? "bg-dv-success"
                  : "bg-dv-danger"
            }`}
          />
          {online === null ? "Prüfe..." : online ? "Dario online" : "Backend offline"}
        </span>
        <button
          onClick={() => logout()}
          className="rounded-dv-sm px-3 py-1.5 text-sm font-medium text-dv-text-secondary hover:bg-dv-surface-secondary"
        >
          Abmelden
        </button>
      </div>
    </header>
  );
}
