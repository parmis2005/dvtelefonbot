// Fallback bewusst auf "localhost" statt "127.0.0.1": Browser behandeln
// beide als unterschiedliche SITES, wodurch das SameSite=Lax-Session-Cookie
// (core/auth.py) bei Cross-Site-Fetches verworfen wird, wenn das Dashboard
// selbst z.B. unter http://localhost:3000 laeuft (siehe .env.example).
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/**
 * Zentraler Fetch-Wrapper: sendet immer credentials (httpOnly Session-Cookie,
 * siehe core/auth.py) und leitet bei 401 direkt zur Login-Seite um - die
 * eigentliche Session-Pruefung passiert ausschliesslich serverseitig im
 * Backend, proxy.ts prueft nur oberflaechlich auf Vorhandensein des Cookies.
 */
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      ...(options.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options.headers,
    },
  });

  if (response.status === 401) {
    // Reiner Fetch-Wrapper ausserhalb von React-Komponenten - kein Zugriff
    // auf useRouter(), daher bewusst ein harter Redirect statt Client-Routing.
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }
    throw new ApiError(401, "Nicht angemeldet");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // keine JSON-Fehlermeldung vorhanden
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.blob()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  postForm: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
};

export function apiFileUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}
