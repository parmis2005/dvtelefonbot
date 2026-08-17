"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import type { Campaign } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { CampaignCreateForm } from "./CampaignCreateForm";
import { CampaignCard } from "./CampaignCard";

export default function KampagnenPage() {
  const { data: campaigns, mutate } = useSWR<Campaign[]>("/api/campaigns", fetcher, {
    refreshInterval: 5000,
  });

  const active = campaigns?.filter((c) => c.status === "RUNNING" || c.status === "PAUSED") ?? [];
  const past = campaigns?.filter((c) => c.status === "COMPLETED" || c.status === "STOPPED") ?? [];

  return (
    <div>
      <PageHeader title="Kampagnen" subtitle="Sammelanrufe erstellen und überwachen" />

      <div className="grid gap-6 lg:grid-cols-2">
        <CampaignCreateForm onCreated={() => mutate()} />

        <div className="space-y-4">
          {active.length > 0 && (
            <div>
              <h2 className="mb-2 text-sm font-semibold text-dv-text-secondary">Laufend</h2>
              <div className="space-y-3">
                {active.map((c) => (
                  <CampaignCard key={c.id} campaignId={c.id} />
                ))}
              </div>
            </div>
          )}

          {past.length > 0 && (
            <div>
              <h2 className="mb-2 text-sm font-semibold text-dv-text-secondary">Abgeschlossen</h2>
              <div className="space-y-3">
                {past.slice(0, 5).map((c) => (
                  <CampaignCard key={c.id} campaignId={c.id} />
                ))}
              </div>
            </div>
          )}

          {active.length === 0 && past.length === 0 && (
            <p className="text-sm text-dv-text-muted">Noch keine Kampagnen erstellt.</p>
          )}
        </div>
      </div>
    </div>
  );
}
