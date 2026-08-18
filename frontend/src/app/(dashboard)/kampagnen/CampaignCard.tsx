"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { Campaign } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";

const STATUS_TONE: Record<string, "neutral" | "accent" | "warm" | "danger" | "success"> = {
  DRAFT: "neutral",
  RUNNING: "success",
  PAUSED: "warm",
  STOPPED: "danger",
  COMPLETED: "accent",
};

export function CampaignCard({ campaignId }: { campaignId: number }) {
  const { data: campaign, mutate } = useSWR<Campaign>(`/api/campaigns/${campaignId}`, fetcher, {
    refreshInterval: 2000,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!campaign) return null;

  async function action(path: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/campaigns/${campaignId}/${path}`);
      mutate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Aktion fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  const progressPct = campaign.total_count
    ? Math.round((campaign.processed_count / campaign.total_count) * 100)
    : 0;
  const freeSlots = Math.max(0, campaign.max_concurrent - campaign.active_count);
  const remaining = Math.max(0, campaign.total_count - campaign.processed_count);

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="font-display text-base font-semibold text-dv-text-primary">
              {campaign.name}
            </div>
            <div className="text-xs text-dv-text-muted">
              Erstellt am {new Date(campaign.created_at).toLocaleString("de-DE")}
            </div>
          </div>
          <Badge tone={STATUS_TONE[campaign.status]}>{campaign.status}</Badge>
        </div>

        <div className="mb-3 h-2 w-full overflow-hidden rounded-dv-pill bg-dv-surface-secondary">
          <div
            className="h-full bg-dv-accent transition-all duration-300"
            style={{ width: `${progressPct}%` }}
          />
        </div>

        <div className="mb-4 grid grid-cols-4 gap-2 text-center text-xs">
          <div>
            <div className="font-display text-lg font-bold text-dv-text-primary">
              {campaign.processed_count}
            </div>
            <div className="text-dv-text-muted">bearbeitet</div>
          </div>
          <div>
            <div className="font-display text-lg font-bold text-dv-text-primary">
              {campaign.active_count}
            </div>
            <div className="text-dv-text-muted">aktiv</div>
          </div>
          <div>
            <div className="font-display text-lg font-bold text-dv-text-primary">{freeSlots}</div>
            <div className="text-dv-text-muted">freie Slots</div>
          </div>
          <div>
            <div className="font-display text-lg font-bold text-dv-text-primary">{remaining}</div>
            <div className="text-dv-text-muted">verbleibend</div>
          </div>
        </div>

        {error && <p className="mb-2 text-sm text-dv-danger">{error}</p>}

        <div className="flex flex-wrap gap-2">
          <Link
            href={`/anrufhistorie?campaign_id=${campaign.id}`}
            className="inline-flex h-8 items-center justify-center rounded-dv-sm border border-dv-border bg-dv-surface px-3 text-sm font-medium text-dv-text-primary transition-colors duration-150 hover:bg-dv-surface-hover"
          >
            Dokumentation ansehen
          </Link>
          {campaign.status === "RUNNING" && (
            <>
              <Button size="sm" variant="secondary" onClick={() => action("pause")} disabled={busy}>
                Pause
              </Button>
              <Button size="sm" variant="danger" onClick={() => action("stop")} disabled={busy}>
                Stoppen
              </Button>
            </>
          )}
          {campaign.status === "PAUSED" && (
            <>
              <Button size="sm" onClick={() => action("resume")} disabled={busy}>
                Fortsetzen
              </Button>
              <Button size="sm" variant="danger" onClick={() => action("stop")} disabled={busy}>
                Stoppen
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
