"use client";

import { useState } from "react";
import Link from "next/link";
import { fetcher } from "@/lib/swr";
import { useTelephonyStatus } from "@/lib/useTelephonyStatus";
import useSWR from "swr";
import type { Call, PromptVersion, VoiceProfile } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { TestCallModal } from "@/components/TestCallModal";

export default function DarioPage() {
  const { data: telephony } = useTelephonyStatus();
  const { data: voices } = useSWR<VoiceProfile[]>("/api/voices", fetcher);
  const { data: prompts } = useSWR<PromptVersion[]>("/api/prompt-versions", fetcher);
  const { data: calls } = useSWR<Call[]>("/api/calls?active_only=true", fetcher, {
    refreshInterval: 5000,
  });
  const [testCallOpen, setTestCallOpen] = useState(false);

  const activeVoice = voices?.find((v) => v.is_active);
  const activePrompt = prompts?.find((p) => p.is_active);

  return (
    <div>
      <PageHeader title="Dario" subtitle="Status des KI-Telefonagenten" />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row label="Telefonie" value="Twilio" ok={telephony?.connected} />
            <Row label="Stimme" value={activeVoice?.name ?? "Keine aktiv"} ok={!!activeVoice} />
            <Row
              label="Prompt-Version"
              value={activePrompt ? `Version ${activePrompt.version_number}` : "Keine aktiv"}
              ok={!!activePrompt}
            />
            <Row label="Aktive Gespräche" value={String(calls?.length ?? 0)} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Aktionen</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <Button onClick={() => setTestCallOpen(true)}>Testanruf</Button>
            <Link href="/stimme">
              <Button variant="secondary" className="w-full">
                Stimme testen
              </Button>
            </Link>
            <Link href="/prompt">
              <Button variant="secondary" className="w-full">
                Prompt bearbeiten
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      <TestCallModal open={testCallOpen} onClose={() => setTestCallOpen(false)} />
    </div>
  );
}

function Row({ label, value, ok }: { label: string; value: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-dv-border-subtle py-2 last:border-0">
      <span className="font-medium text-dv-text-primary">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-dv-text-secondary">{value}</span>
        {ok !== undefined && <Badge tone={ok ? "success" : "danger"}>{ok ? "OK" : "Fehler"}</Badge>}
      </div>
    </div>
  );
}
