"use client";

import { createContext, ReactNode, useCallback, useContext } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api } from "@/lib/api";
import { fetcher } from "@/lib/swr";

/**
 * Client-seitige Auth-Gate: der Browser spricht das Backend cross-origin an
 * (siehe src/lib/api.ts), das Session-Cookie (core/auth.py) ist daher nur
 * fuer die Backend-Origin sichtbar - ein Next.js-proxy.ts koennte dieses
 * Cookie gar nicht lesen. Die echte Durchsetzung passiert ohnehin
 * ausschliesslich im Backend (jede geschuetzte Route antwortet mit 401 ohne
 * gueltige Session) - dieser Context sorgt nur fuer eine saubere
 * Weiterleitung im UI statt eines leeren/fehlerhaften Dashboards.
 *
 * WICHTIG (vormals Ursache fuer ungewollte Zwangs-Logouts): `authenticated`
 * darf NUR dann `false` werden, wenn das Backend das ausdruecklich
 * bestaetigt hat (GET /api/auth/me antwortet immer mit 200 und liefert
 * `{authenticated: false}`, wenn keine gueltige Session vorliegt - das ist
 * die einzige echte "confirmed logged out"-Antwort). Ein fehlgeschlagener
 * fetch (`error`, z.B. Backend kurzzeitig nicht erreichbar, Netzwerkfehler,
 * ein Backend-Neustart mitten im Request) ist KEINE Bestaetigung eines
 * abgelaufenen Logins - in diesem Fall bleibt der zuletzt bekannte Zustand
 * erhalten (bzw. `null`/"wird noch geprueft", falls noch nie erfolgreich
 * geladen), statt den Nutzer faelschlich auf die Login-Seite zu werfen.
 * SWR versucht fehlgeschlagene Anfragen daher automatisch mit Backoff erneut
 * (statt nach dem ersten Fehler dauerhaft haengen zu bleiben) und prueft bei
 * Fokus-Rueckkehr/Netzwerk-Wiederverbindung erneut - so heilt ein
 * voruebergehendes Problem von selbst aus, sobald das Backend wieder
 * erreichbar ist.
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
  const { data, mutate } = useSWR<{ authenticated: boolean }>("/api/auth/me", fetcher, {
    errorRetryCount: 5,
    errorRetryInterval: 3000,
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    // Absichtlich kein `error`-Zweig, der `authenticated` auf `false` setzt -
    // siehe Docstring oben. Ein fehlender/veralteter `data`-Wert bleibt
    // schlicht `null` ("wird noch geprueft"), bis entweder ein echtes
    // Ergebnis eintrifft oder ein Retry erfolgreich ist.
  });

  const authenticated = data ? data.authenticated : null;

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
