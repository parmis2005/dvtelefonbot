"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import type { TelephonyStatus } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { TestCallModal } from "@/components/TestCallModal";

export default function TelefoniePage() {
  const { data: status, isLoading } = useSWR<TelephonyStatus>("/api/telephony/status", fetcher, {
    refreshInterval: 20000,
  });
  const [testCallOpen, setTestCallOpen] = useState(false);

  return (
    <div>
      <PageHeader title="Telefonie" subtitle="Twilio-Verbindung und Testanrufe" />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Verbindungsstatus</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {isLoading && <p className="text-dv-text-muted">Prüfe...</p>}
            {status && (
              <>
                <Row label="Provider" value="Twilio" />
                <Row
                  label="Status"
                  value={status.detail}
                  badge={
                    <Badge tone={status.connected ? "success" : "danger"}>
                      {status.connected ? "Verbunden" : "Fehler"}
                    </Badge>
                  }
                />
                <Row label="Caller ID" value={status.caller_id ?? "Nicht konfiguriert"} />
                <Row label="Account SID" value={status.account_sid_masked ?? "–"} />
                <Row
                  label="Öffentliche URL"
                  value={status.public_base_url_configured ? "Konfiguriert" : "Fehlt"}
                  badge={
                    <Badge tone={status.public_base_url_configured ? "success" : "danger"}>
                      {status.public_base_url_configured ? "OK" : "Fehlt"}
                    </Badge>
                  }
                />
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Testanruf</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-4 text-sm text-dv-text-secondary">
              Löst einen echten Anruf über die vollständige Dario-Gesprächs-Engine aus (kein
              Ansageband).
            </p>
            <Button onClick={() => setTestCallOpen(true)} disabled={!status?.connected}>
              Testanruf starten
            </Button>
          </CardContent>
        </Card>
      </div>

      <TestCallModal open={testCallOpen} onClose={() => setTestCallOpen(false)} />
    </div>
  );
}

function Row({ label, value, badge }: { label: string; value: string; badge?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-dv-border-subtle py-2 last:border-0">
      <span className="font-medium text-dv-text-primary">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-dv-text-secondary">{value}</span>
        {badge}
      </div>
    </div>
  );
}
