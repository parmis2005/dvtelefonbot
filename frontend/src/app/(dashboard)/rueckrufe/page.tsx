"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { Lead } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

type CallbackState = "offen" | "überfällig" | "erledigt";

function callbackState(lead: Lead): CallbackState {
  if (lead.status !== "CALLBACK") return "erledigt";
  if (lead.callback_at && new Date(lead.callback_at).getTime() < Date.now()) return "überfällig";
  return "offen";
}

const STATE_TONE: Record<CallbackState, "warm" | "danger" | "success"> = {
  offen: "warm",
  überfällig: "danger",
  erledigt: "success",
};

export default function RueckrufePage() {
  const { data: leads, mutate } = useSWR<Lead[]>("/api/leads", fetcher, { refreshInterval: 15000 });
  const [busyId, setBusyId] = useState<number | null>(null);

  const callbackLeads = (leads ?? [])
    .filter((l) => l.callback_at || l.status === "CALLBACK")
    .sort((a, b) => callbackState(a).localeCompare(callbackState(b)));

  async function callNow(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.post("/api/calls/twilio", { lead_id: lead.id });
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Anruf konnte nicht gestartet werden.");
    } finally {
      setBusyId(null);
    }
  }

  async function markDone(lead: Lead) {
    setBusyId(lead.id);
    try {
      await api.patch(`/api/leads/${lead.id}`, { status: "CALLED" });
      mutate();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Aktion fehlgeschlagen.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <PageHeader title="Rückrufe" subtitle={`${callbackLeads.length} Rückrufe`} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {callbackLeads.map((lead) => {
          const state = callbackState(lead);
          return (
            <Card key={lead.id}>
              <CardContent className="pt-6">
                <div className="mb-2 flex items-start justify-between">
                  <div>
                    <div className="font-display text-base font-semibold text-dv-text-primary">
                      {lead.unternehmen}
                    </div>
                    <div className="text-xs text-dv-text-muted">
                      {lead.ansprechpartner ?? lead.telefonnummer}
                    </div>
                  </div>
                  <Badge tone={STATE_TONE[state]}>{state}</Badge>
                </div>
                {lead.callback_at && (
                  <p className="text-xs text-dv-text-muted">
                    Vereinbart für {new Date(lead.callback_at).toLocaleString("de-DE")}
                  </p>
                )}
                {lead.callback_note && (
                  <p className="mt-2 text-sm text-dv-text-secondary">{lead.callback_note}</p>
                )}
                {state !== "erledigt" && (
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" disabled={busyId === lead.id} onClick={() => callNow(lead)}>
                      Jetzt anrufen
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busyId === lead.id}
                      onClick={() => markDone(lead)}
                    >
                      Erledigt
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
        {callbackLeads.length === 0 && (
          <p className="text-sm text-dv-text-muted">Keine Rückrufe vorhanden.</p>
        )}
      </div>
    </div>
  );
}
