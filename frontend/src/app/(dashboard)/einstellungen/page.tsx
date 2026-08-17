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
      <PageHeader title="Einstellungen" subtitle="Laufzeit-Konfiguration von Dario" />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Kampagnen</CardTitle>
          </CardHeader>
          <CardContent>
            {settings ? (
              <SettingsForm key={JSON.stringify(settings.values)} initial={settings} onSaved={() => mutate()} />
            ) : (
              <p className="text-sm text-dv-text-muted">Lädt...</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Weitere Konfiguration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <InfoRow label="Agent-Name" value={settings?.readonly_info.agent_name ?? "–"} />
            <InfoRow label="Firma" value={settings?.readonly_info.company_name ?? "–"} />
            <InfoRow label="Standort" value={settings?.readonly_info.company_location ?? "–"} />
            <InfoRow label="Anruf-Cooldown (s)" value={settings?.readonly_info.call_cooldown_seconds ?? "–"} />
            <InfoRow label="Warte-Timeout (s)" value={settings?.readonly_info.wait_timeout_seconds ?? "–"} />
            <InfoRow label="Stille-Timeout (s)" value={settings?.readonly_info.silence_timeout_seconds ?? "–"} />
            <InfoRow
              label="Aktive Prompt-Version"
              value={activePrompt ? `Version ${activePrompt.version_number}` : "–"}
            />
            <InfoRow label="Aktive Stimme" value={activeVoice?.name ?? "–"} />
            <p className="pt-2 text-xs text-dv-text-muted">
              Diese Werte stammen aus der .env-Konfiguration des Backends und sind hier nur zur
              Übersicht angezeigt — Änderung erfordert aktuell einen Zugriff auf die
              Server-Konfiguration.
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
