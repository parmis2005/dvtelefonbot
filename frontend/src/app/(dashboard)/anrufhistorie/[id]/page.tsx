"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useParams } from "next/navigation";
import { fetcher } from "@/lib/swr";
import type { Call, Lead } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";

interface TranscriptTurn {
  speaker: "dario" | "kunde" | string;
  text: string;
  timestamp: string;
}

function parseTranscript(raw: string | null | undefined): TranscriptTurn[] {
  if (!raw) return [];
  try {
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

export default function CallDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: call } = useSWR<Call>(`/api/calls/${id}`, fetcher);
  const { data: leads } = useSWR<Lead[]>("/api/leads", fetcher);
  const [showTechnical, setShowTechnical] = useState(false);

  const lead = leads?.find((l) => l.id === call?.lead_id);
  const turns = parseTranscript(call?.transcript);

  if (!call) {
    return <p className="text-sm text-dv-text-muted">Lädt...</p>;
  }

  return (
    <div>
      <Link href="/anrufhistorie" className="mb-4 inline-block text-sm text-dv-accent hover:underline">
        ← Zurück zur Anrufhistorie
      </Link>

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-bold text-dv-text-primary">
            {lead?.unternehmen ?? `Lead #${call.lead_id}`}
          </h1>
          <p className="mt-1 text-sm text-dv-text-secondary">
            {call.started_at ? new Date(call.started_at).toLocaleString("de-DE") : "–"} ·{" "}
            {lead?.telefonnummer}
          </p>
        </div>
        <div className="flex gap-2">
          <Badge tone="neutral">{call.status}</Badge>
          {call.result && <Badge tone="accent">{call.result}</Badge>}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Transkript</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {turns.length === 0 && (
                <p className="text-sm text-dv-text-muted">Kein Transkript verfügbar.</p>
              )}
              {turns.map((turn, i) => (
                <div
                  key={i}
                  className={cn("flex", turn.speaker === "dario" ? "justify-start" : "justify-end")}
                >
                  <div
                    className={cn(
                      "max-w-[80%] rounded-dv-md px-4 py-2 text-sm",
                      turn.speaker === "dario"
                        ? "bg-dv-surface-secondary text-dv-text-primary"
                        : "bg-dv-accent text-white"
                    )}
                  >
                    <div className="mb-1 text-[10px] uppercase tracking-wide opacity-70">
                      {turn.speaker === "dario" ? "Dario" : "Kunde"}
                    </div>
                    {turn.text}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Zusammenfassung</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="whitespace-pre-wrap font-sans text-sm text-dv-text-secondary">
                {call.summary ?? "Keine Zusammenfassung verfügbar."}
              </pre>
            </CardContent>
          </Card>

          <Card>
            <button
              className="flex w-full items-center justify-between px-6 py-4 text-left"
              onClick={() => setShowTechnical((v) => !v)}
            >
              <span className="font-display text-base font-semibold text-dv-text-primary">
                Technische Details
              </span>
              <span className="text-dv-text-muted">{showTechnical ? "−" : "+"}</span>
            </button>
            {showTechnical && (
              <CardContent className="space-y-2 text-sm">
                <DetailRow label="Call-ID" value={String(call.id)} />
                <DetailRow label="Lead-ID" value={String(call.lead_id)} />
                <DetailRow label="Kampagne" value={call.campaign_id ? String(call.campaign_id) : "–"} />
                <DetailRow label="Twilio Call-SID" value={call.twilio_call_sid ?? "–"} />
                <DetailRow label="Status" value={call.status} />
                <DetailRow label="Ergebnis" value={call.result ?? "–"} />
                <DetailRow
                  label="Beendet"
                  value={call.ended_at ? new Date(call.ended_at).toLocaleString("de-DE") : "–"}
                />
                <DetailRow label="Dauer (s)" value={call.duration != null ? String(call.duration) : "–"} />
              </CardContent>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-dv-border-subtle py-1.5 last:border-0">
      <span className="text-dv-text-muted">{label}</span>
      <span className="font-mono text-xs text-dv-text-primary">{value}</span>
    </div>
  );
}
