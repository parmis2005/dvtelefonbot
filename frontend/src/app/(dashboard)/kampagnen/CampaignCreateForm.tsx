"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { Campaign, Lead, TelephonyStatus, VoiceProfile, PromptVersion } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import { Modal } from "@/components/ui/Modal";

export function CampaignCreateForm({ onCreated }: { onCreated: (c: Campaign) => void }) {
  const { data: leads } = useSWR<Lead[]>("/api/leads", fetcher);
  const { data: telephony } = useSWR<TelephonyStatus>("/api/telephony/status", fetcher);
  const { data: voices } = useSWR<VoiceProfile[]>("/api/voices", fetcher);
  const { data: prompts } = useSWR<PromptVersion[]>("/api/prompt-versions", fetcher);

  const [name, setName] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [concurrency, setConcurrency] = useState(10);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Synchronisiert mit sessionStorage (externes System, von der Kontakte-
  // Seite befuellt) - server-seitig existiert sessionStorage nicht, daher
  // absichtlich als Mount-Effekt statt als useState-Initializer (sonst
  // Hydration-Mismatch zwischen SSR- und Client-Erstrender).
  useEffect(() => {
    const raw = sessionStorage.getItem("dv-campaign-lead-ids");
    if (raw) {
      try {
        const ids: number[] = JSON.parse(raw);
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSelected(new Set(ids));
      } catch {
        // ignore
      }
      sessionStorage.removeItem("dv-campaign-lead-ids");
    }
  }, []);

  const callableLeads = useMemo(
    () => (leads ?? []).filter((l) => !l.do_not_call),
    [leads]
  );
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return callableLeads;
    return callableLeads.filter(
      (l) =>
        l.unternehmen.toLowerCase().includes(q) || l.telefonnummer.includes(q)
    );
  }, [callableLeads, search]);

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  const activeVoice = voices?.find((v) => v.is_active);
  const activePrompt = prompts?.find((p) => p.is_active);

  async function handleConfirmStart() {
    setSubmitting(true);
    setError(null);
    try {
      const campaign = await api.post<Campaign>("/api/campaigns", {
        name: name || `Kampagne ${new Date().toLocaleDateString("de-DE")}`,
        lead_ids: Array.from(selected),
        max_concurrent: concurrency,
      });
      const started = await api.post<Campaign>(`/api/campaigns/${campaign.id}/start`);
      setConfirmOpen(false);
      setSelected(new Set());
      setName("");
      onCreated(started);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Kampagne konnte nicht gestartet werden.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Neue Sammelanruf-Kampagne</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="mb-4 grid gap-3 sm:grid-cols-2">
          <div>
            <Label>Name der Kampagne</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="z.B. Erstansprache Mai" />
          </div>
          <div>
            <Label>Parallele Gespräche</Label>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setConcurrency((c) => Math.max(1, c - 1))}
              >
                −
              </Button>
              <span className="w-8 text-center font-display text-lg font-semibold">{concurrency}</span>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setConcurrency((c) => Math.min(10, c + 1))}
              >
                +
              </Button>
              <span className="text-xs text-dv-text-muted">von max. 10</span>
            </div>
          </div>
        </div>

        <Label>Kontakte auswählen ({selected.size} ausgewählt)</Label>
        <Input
          placeholder="Suchen..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mb-2 mt-1"
        />
        <div className="max-h-64 overflow-auto rounded-dv-sm border border-dv-border-subtle">
          {filtered.map((lead) => (
            <label
              key={lead.id}
              className="flex cursor-pointer items-center gap-3 border-b border-dv-border-subtle px-3 py-2 text-sm last:border-0 hover:bg-dv-surface-hover"
            >
              <input type="checkbox" checked={selected.has(lead.id)} onChange={() => toggle(lead.id)} />
              <span className="font-medium text-dv-text-primary">{lead.unternehmen}</span>
              <span className="text-dv-text-muted">{lead.telefonnummer}</span>
            </label>
          ))}
          {filtered.length === 0 && (
            <p className="px-3 py-6 text-center text-sm text-dv-text-muted">Keine Kontakte gefunden.</p>
          )}
        </div>

        <div className="mt-4 flex justify-end">
          <Button disabled={selected.size === 0} onClick={() => setConfirmOpen(true)}>
            Jetzt anrufen ({selected.size})
          </Button>
        </div>
      </CardContent>

      <Modal open={confirmOpen} onClose={() => setConfirmOpen(false)} title="Kampagne starten?">
        <div className="space-y-2 text-sm">
          <Row label="Kontakte" value={String(selected.size)} />
          <Row label="Parallele Gespräche" value={String(concurrency)} />
          <Row label="Agent" value="Dario" />
          <Row label="Stimme" value={activeVoice?.name ?? "Standard"} />
          <Row label="Prompt" value={activePrompt ? `Version ${activePrompt.version_number}` : "Standard"} />
          <Row label="Caller ID" value={telephony?.caller_id ?? "Nicht konfiguriert"} />
        </div>
        {!telephony?.connected && (
          <p className="mt-3 text-sm text-dv-danger">
            Twilio ist nicht verbunden — die Kampagne kann keine echten Anrufe starten.
          </p>
        )}
        {error && <p className="mt-3 text-sm text-dv-danger">{error}</p>}
        <p className="mt-4 text-xs text-dv-text-muted">
          Dies löst echte, kostenpflichtige Anrufe aus.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setConfirmOpen(false)}>
            Abbrechen
          </Button>
          <Button onClick={handleConfirmStart} disabled={submitting}>
            {submitting ? "Startet..." : "Jetzt anrufen"}
          </Button>
        </div>
      </Modal>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between border-b border-dv-border-subtle py-1.5 last:border-0">
      <span className="text-dv-text-muted">{label}</span>
      <span className="font-medium text-dv-text-primary">{value}</span>
    </div>
  );
}
