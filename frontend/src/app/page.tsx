"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function RootPage() {
  const { authenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (authenticated === true) {
      router.replace("/uebersicht");
    } else if (authenticated === false) {
      router.replace("/login");
    }
  }, [authenticated, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-dv-background">
      <p className="text-sm text-dv-text-muted">Lade...</p>
    </div>
  );
}
