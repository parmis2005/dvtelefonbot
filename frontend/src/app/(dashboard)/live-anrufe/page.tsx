"use client";

import { useEffect, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { useLiveStatus } from "@/lib/useLiveStatus";
import { api, ApiError } from "@/lib/api";

function Duration({ startedAt }: { startedAt: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, []);
  if (!startedAt) return <span>–</span>;
  const seconds = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  return (
    <span>
      {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
    </span>
  );
}

const STATUS_TONE: Record<string, "neutral" | "accent" | "warm" | "success"> = {
  CREATED: "neutral",
  RINGING: "warm",
  ANSWERED: "success",
};

export default function LiveAnrufePage() {
  const { calls, connected } = useLiveStatus();
  const [endingId, setEndingId] = useState<number | null>(null);

  async function endCall(callId: number) {
    setEndingId(callId);
    try {
      await api.post(`/api/calls/${callId}/hangup`);
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Anruf konnte nicht beendet werden.");
    } finally {
      setEndingId(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Live-Anrufe"
        subtitle={connected ? `${calls.length} aktive Gespräche` : "Verbinde..."}
      />

      {calls.length === 0 && (
        <p className="text-sm text-dv-text-muted">Aktuell keine aktiven Gespräche.</p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {calls.map((call) => (
          <Card key={call.call_id}>
            <CardContent className="pt-6">
              <div className="mb-2 flex items-start justify-between">
                <div>
                  <div className="font-display text-base font-semibold text-dv-text-primary">
                    {call.unternehmen ?? "Unbekannt"}
                  </div>
                  <div className="text-xs text-dv-text-muted">
                    {call.ansprechpartner ?? call.telefonnummer}
                  </div>
                </div>
                <Badge tone={STATUS_TONE[call.status] ?? "neutral"}>{call.status_label}</Badge>
              </div>
              <div className="mt-3 flex items-center justify-between text-sm text-dv-text-secondary">
                <span>
                  Dauer: <Duration startedAt={call.started_at} />
                </span>
                {call.status === "ANSWERED" && (
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={endingId === call.call_id}
                    onClick={() => endCall(call.call_id)}
                  >
                    Gespräch beenden
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
