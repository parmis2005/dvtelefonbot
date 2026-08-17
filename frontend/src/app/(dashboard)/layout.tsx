"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Header } from "@/components/Header";
import { NavSidebar } from "@/components/NavSidebar";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { authenticated } = useAuth();
  const router = useRouter();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (authenticated === false) {
      router.replace("/login");
    }
  }, [authenticated, router]);

  if (authenticated !== true) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-dv-background">
        <p className="text-sm text-dv-text-muted">Lade...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <Header onMenuToggle={() => setMobileNavOpen((v) => !v)} />
      <div className="flex flex-1">
        <aside className="hidden w-56 shrink-0 border-r border-dv-border-subtle bg-dv-surface md:block">
          <NavSidebar />
        </aside>
        {mobileNavOpen && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div
              className="absolute inset-0 bg-dv-text-primary/30"
              onClick={() => setMobileNavOpen(false)}
            />
            <aside className="absolute left-0 top-0 h-full w-64 bg-dv-surface shadow-dv-lg">
              <NavSidebar onNavigate={() => setMobileNavOpen(false)} />
            </aside>
          </div>
        )}
        <main className="flex-1 bg-dv-background p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
