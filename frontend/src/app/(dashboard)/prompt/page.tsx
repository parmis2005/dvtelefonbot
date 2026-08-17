"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { PromptVersion } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PromptEditor } from "./PromptEditor";

export default function PromptPage() {
  const { data: versions, mutate } = useSWR<PromptVersion[]>("/api/prompt-versions", fetcher);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const active = versions?.find((v) => v.is_active);
  const sorted = [...(versions ?? [])].sort((a, b) => b.version_number - a.version_number);

  async function restore(versionId: number) {
    setRestoringId(versionId);
    setError(null);
    try {
      await api.post(`/api/prompt-versions/${versionId}/activate`);
      mutate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Wiederherstellen fehlgeschlagen.");
    } finally {
      setRestoringId(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Prompt"
        subtitle="Neue Gespräche verwenden automatisch die zuletzt gespeicherte Version — laufende Gespräche behalten ihre gestartete Version."
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>
                {active
                  ? `Version ${active.version_number} · ${new Date(active.created_at).toLocaleString("de-DE")}`
                  : "Editor"}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {active ? (
                <PromptEditor key={active.id} initialContent={active.content} onSaved={() => mutate()} />
              ) : (
                <p className="text-sm text-dv-text-muted">Lädt...</p>
              )}
            </CardContent>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Versionen</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {error && <p className="text-sm text-dv-danger">{error}</p>}
            {sorted.map((v) => (
              <div
                key={v.id}
                className="flex items-center justify-between rounded-dv-sm border border-dv-border-subtle px-3 py-2"
              >
                <div>
                  <div className="text-sm font-medium text-dv-text-primary">
                    Version {v.version_number}
                  </div>
                  <div className="text-xs text-dv-text-muted">
                    {new Date(v.created_at).toLocaleString("de-DE")}
                  </div>
                </div>
                {v.is_active ? (
                  <Badge tone="success">Aktiv</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={restoringId === v.id}
                    onClick={() => restore(v.id)}
                  >
                    Wiederherstellen
                  </Button>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
