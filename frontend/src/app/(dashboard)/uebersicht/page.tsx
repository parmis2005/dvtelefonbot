"use client";

import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { useTelephonyStatus } from "@/lib/useTelephonyStatus";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/Badge";
import type { Call, Lead, PromptVersion, VoiceProfile } from "@/lib/types";

function StatCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="dv-eyebrow mb-2">{label}</div>
        <div className="font-display text-3xl font-bold text-dv-text-primary">{value}</div>
        {hint && <div className="mt-1 text-xs text-dv-text-muted">{hint}</div>}
      </CardContent>
    </Card>
  );
}

function isToday(iso: string | null): boolean {
  if (!iso) return false;
  const d = new Date(iso);
  const now = new Date();
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  );
}

export default function UebersichtPage() {
  const { data: leads } = useSWR<Lead[]>("/api/leads", fetcher, { refreshInterval: 15000 });
  const { data: calls } = useSWR<Call[]>("/api/calls", fetcher, { refreshInterval: 10000 });
  const { data: telephony } = useTelephonyStatus();
  const { data: promptVersions } = useSWR<PromptVersion[]>("/api/prompt-versions", fetcher);
  const { data: voices } = useSWR<VoiceProfile[]>("/api/voices", fetcher);

  const todaysCalls = calls?.filter((c) => isToday(c.started_at)) ?? [];
  const activeCalls = calls?.filter((c) => ["CREATED", "RINGING", "ANSWERED"].includes(c.status)) ?? [];
  const interessenten = leads?.filter((l) => ["INTERESTED", "QUALIFIED", "DESIGN_REQUESTED"].includes(l.status)) ?? [];
  const rueckrufe = leads?.filter((l) => l.status === "CALLBACK") ?? [];
  const nichtErreicht = todaysCalls.filter((c) => c.status === "NO_ANSWER" || c.status === "BUSY");
  const completedWithDuration = todaysCalls.filter((c) => c.duration != null);
  const avgDuration = completedWithDuration.length
    ? Math.round(
        completedWithDuration.reduce((sum, c) => sum + (c.duration ?? 0), 0) /
          completedWithDuration.length
      )
    : 0;

  const activePrompt = promptVersions?.find((p) => p.is_active);
  const activeVoice = voices?.find((v) => v.is_active);

  return (
    <div>
      <PageHeader title="Übersicht" subtitle="Willkommen zurück — hier ist der aktuelle Stand." />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <StatCard label="Heutige Anrufe" value={todaysCalls.length} />
        <StatCard label="Aktive Gespräche" value={activeCalls.length} />
        <StatCard label="Interessenten" value={interessenten.length} />
        <StatCard label="Rückrufe" value={rueckrufe.length} />
        <StatCard label="Nicht erreicht" value={nichtErreicht.length} hint="heute" />
        <StatCard
          label="Ø Gesprächsdauer"
          value={avgDuration ? `${Math.floor(avgDuration / 60)}:${String(avgDuration % 60).padStart(2, "0")}` : "–"}
        />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Systemstatus</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatusRow
              label="Twilio"
              ok={telephony?.connected}
              detail={telephony?.detail ?? "Prüfe..."}
            />
            <StatusRow
              label="Stimme"
              ok={!!activeVoice}
              detail={activeVoice ? activeVoice.name : "Keine aktive Stimme"}
            />
            <StatusRow
              label="Prompt"
              ok={!!activePrompt}
              detail={activePrompt ? `Version ${activePrompt.version_number}` : "Kein aktiver Prompt"}
            />
            <StatusRow label="Backend" ok={true} detail="Erreichbar" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Schnellstart</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Link
              href="/kontakte"
              className="rounded-dv-sm border border-dv-border-subtle px-4 py-3 text-sm font-medium text-dv-text-primary hover:bg-dv-surface-secondary"
            >
              + Kontakt hinzufügen / CSV importieren
            </Link>
            <Link
              href="/kampagnen"
              className="rounded-dv-sm border border-dv-border-subtle px-4 py-3 text-sm font-medium text-dv-text-primary hover:bg-dv-surface-secondary"
            >
              Sammelanruf starten
            </Link>
            <Link
              href="/prompt"
              className="rounded-dv-sm border border-dv-border-subtle px-4 py-3 text-sm font-medium text-dv-text-primary hover:bg-dv-surface-secondary"
            >
              Prompt bearbeiten
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatusRow({ label, ok, detail }: { label: string; ok?: boolean; detail: string }) {
  return (
    <div className="flex items-center justify-between border-b border-dv-border-subtle py-2 last:border-0">
      <span className="text-sm font-medium text-dv-text-primary">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs text-dv-text-muted">{detail}</span>
        <Badge tone={ok ? "success" : "danger"}>{ok ? "OK" : "Fehler"}</Badge>
      </div>
    </div>
  );
}
