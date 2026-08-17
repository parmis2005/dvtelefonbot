"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import type { DashboardSettings, PromptVersion, VoiceProfile } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { SettingsForm } from "./SettingsForm";

export default function EinstellungenPage() {
  const { data: settings, mutate } = useSWR<DashboardSettings>("/api/settings", fetcher);
  const { data: prompts } = useSWR<PromptVersion[]>("/api/prompt-versions", fetcher);
  const { data: voices } = useSWR<VoiceProfile[]>("/api/voices", fetcher);

  const activePrompt = prompts?.find((p) => p.is_active);
  const activeVoice = voices?.find((v) => v.is_active);

  return (
    <div>
      <PageHeader
        title="Einstellungen"
        subtitle="Laufzeit-Konfiguration von Dario — wirkt sofort auf alle neuen Anrufe, ohne Backend-Neustart"
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Konfiguration</CardTitle>
          </CardHeader>
          <CardContent>
            {settings ? (
              <SettingsForm
                key={JSON.stringify(settings.values)}
                initial={settings}
                onSaved={() => mutate()}
              />
            ) : (
              <p className="text-sm text-dv-text-muted">Lädt...</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Aktive Konfiguration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <InfoRow
              label="Aktive Prompt-Version"
              value={activePrompt ? `Version ${activePrompt.version_number}` : "–"}
            />
            <InfoRow label="Aktive Stimme" value={activeVoice?.name ?? "–"} />
            <p className="pt-2 text-xs text-dv-text-muted">
              Werden auf den Seiten Prompt und Stimme verwaltet.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-dv-border-subtle py-2 last:border-0 text-sm">
      <span className="font-medium text-dv-text-primary">{label}</span>
      <span className="text-dv-text-secondary">{value}</span>
    </div>
  );
}
