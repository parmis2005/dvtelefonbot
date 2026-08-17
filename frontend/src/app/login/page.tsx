"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import { Card, CardContent } from "@/components/ui/Card";

export default function LoginPage() {
  const { authenticated, login } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (authenticated) {
      router.replace("/uebersicht");
    }
  }, [authenticated, router]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username, password);
      router.replace("/uebersicht");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-dv-background px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="dv-eyebrow mb-2">Digital Vision</div>
          <h1 className="font-display text-2xl font-bold text-dv-text-primary">
            DVTelefonbot Dashboard
          </h1>
          <p className="mt-1 text-sm text-dv-text-secondary">Anmelden, um fortzufahren</p>
        </div>
        <Card>
          <CardContent className="pt-6">
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Label htmlFor="username">Benutzername</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
              <div>
                <Label htmlFor="password">Passwort</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
              {error && <p className="text-sm text-dv-danger">{error}</p>}
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Anmelden..." : "Anmelden"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
