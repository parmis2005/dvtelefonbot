"use client";

import { createContext, ReactNode, useCallback, useContext } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { fetcher } from "@/lib/swr";

/**
 * Client-seitige Auth-Gate: der Browser spricht das Backend cross-origin an
 * (siehe src/lib/api.ts), das Session-Cookie (core/auth.py) ist daher nur
 * fuer die Backend-Origin sichtbar - ein serverseitiges Next.js-proxy.ts
 * koennte dieses Cookie gar nicht lesen. Die echte Durchsetzung passiert
 * ohnehin ausschliesslich im Backend (jede geschuetzte Route antwortet mit
 * 401 ohne gueltige Session) - dieser Context sorgt nur fuer eine saubere
 * Weiterleitung im UI statt eines leeren/fehlerhaften Dashboards.
 *
 * Nutzt SWR statt eines eigenen useEffect+setState fuer die Session-Pruefung
 * beim Laden - SWR kapselt den Datenabruf-Effekt intern.
 */
interface AuthState {
  authenticated: boolean | null; // null = wird noch geprueft
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data, error, mutate } = useSWR<{ authenticated: boolean }>("/api/auth/me", fetcher, {
    shouldRetryOnError: false,
    revalidateOnFocus: false,
  });

  const authenticated = data ? data.authenticated : error ? false : null;

  const login = useCallback(
    async (username: string, password: string) => {
      await api.post("/api/auth/login", { username, password });
      await mutate({ authenticated: true });
    },
    [mutate]
  );

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    await mutate({ authenticated: false });
    router.push("/login");
  }, [router, mutate]);

  return (
    <AuthContext.Provider value={{ authenticated, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth muss innerhalb von AuthProvider verwendet werden");
  return ctx;
}
