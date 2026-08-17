"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { fetcher } from "@/lib/swr";
import type { Call, CallResultValue, Lead } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Select } from "@/components/ui/Input";

const RESULT_LABELS: Record<string, string> = {
  INTERESTED: "Interessiert",
  NOT_INTERESTED: "Kein Interesse",
  DESIGN_SENT: "Entwurf versendet",
  CALLBACK_REQUESTED: "Rückruf gewünscht",
  DO_NOT_CALL: "Do-Not-Call",
  GATEKEEPER_ONLY: "Nur Empfang",
  NO_ANSWER: "Nicht erreicht",
  UNKNOWN: "Unklar",
};

const RESULT_TONE: Record<string, "neutral" | "accent" | "warm" | "danger" | "success"> = {
  INTERESTED: "success",
  NOT_INTERESTED: "danger",
  DESIGN_SENT: "success",
  CALLBACK_REQUESTED: "warm",
  DO_NOT_CALL: "danger",
  GATEKEEPER_ONLY: "neutral",
  NO_ANSWER: "neutral",
  UNKNOWN: "neutral",
};

function formatDuration(seconds: number | null): string {
  if (seconds == null) return "–";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export default function AnrufhistoriePage() {
  const { data: calls } = useSWR<Call[]>("/api/calls", fetcher, { refreshInterval: 15000 });
  const { data: leads } = useSWR<Lead[]>("/api/leads", fetcher);
  const [filter, setFilter] = useState<CallResultValue | "ALLE">("ALLE");

  const leadMap = useMemo(() => {
    const map = new Map<number, Lead>();
    leads?.forEach((l) => map.set(l.id, l));
    return map;
  }, [leads]);

  const sorted = useMemo(() => {
    const list = [...(calls ?? [])].sort(
      (a, b) => new Date(b.started_at ?? 0).getTime() - new Date(a.started_at ?? 0).getTime()
    );
    if (filter === "ALLE") return list;
    return list.filter((c) => c.result === filter);
  }, [calls, filter]);

  return (
    <div>
      <PageHeader title="Anrufhistorie" subtitle={`${calls?.length ?? 0} Anrufe insgesamt`} />

      <div className="mb-4">
        <Select
          value={filter}
          onChange={(e) => setFilter(e.target.value as CallResultValue | "ALLE")}
          className="max-w-xs"
        >
          <option value="ALLE">Alle Ergebnisse</option>
          {Object.entries(RESULT_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </Select>
      </div>

      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-dv-border-subtle text-xs text-dv-text-muted">
            <tr>
              <th className="px-4 py-3">Datum</th>
              <th className="px-4 py-3">Unternehmen</th>
              <th className="px-4 py-3">Nummer</th>
              <th className="px-4 py-3">Dauer</th>
              <th className="px-4 py-3">Ergebnis</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((call) => {
              const lead = leadMap.get(call.lead_id);
              return (
                <tr
                  key={call.id}
                  className="cursor-pointer border-b border-dv-border-subtle last:border-0 hover:bg-dv-surface-hover"
                >
                  <td className="px-4 py-3 text-dv-text-secondary">
                    <Link href={`/anrufhistorie/${call.id}`} className="block">
                      {call.started_at ? new Date(call.started_at).toLocaleString("de-DE") : "–"}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-medium text-dv-text-primary">
                    <Link href={`/anrufhistorie/${call.id}`} className="block">
                      {lead?.unternehmen ?? `Lead #${call.lead_id}`}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-dv-text-secondary">{lead?.telefonnummer ?? "–"}</td>
                  <td className="px-4 py-3 text-dv-text-secondary">{formatDuration(call.duration)}</td>
                  <td className="px-4 py-3">
                    {call.result ? (
                      <Badge tone={RESULT_TONE[call.result] ?? "neutral"}>
                        {RESULT_LABELS[call.result] ?? call.result}
                      </Badge>
                    ) : (
                      "–"
                    )}
                  </td>
                  <td className="px-4 py-3 text-dv-text-secondary">{call.status}</td>
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-dv-text-muted">
                  Keine Anrufe gefunden.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
