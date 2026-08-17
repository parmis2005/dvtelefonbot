"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import type { DashboardSettings } from "@/lib/types";

interface FormState {
  agent_name: string;
  company_name: string;
  company_location: string;
  wait_timeout_seconds: string;
  silence_timeout_seconds: string;
  call_cooldown_seconds: string;
  campaign_default_concurrency: string;
  campaign_max_concurrency: string;
  campaign_pause_between_calls_seconds: string;
}

function toFormState(values: Record<string, string>): FormState {
  return {
    agent_name: values.agent_name ?? "",
    company_name: values.company_name ?? "",
    company_location: values.company_location ?? "",
    wait_timeout_seconds: values.wait_timeout_seconds ?? "",
    silence_timeout_seconds: values.silence_timeout_seconds ?? "",
    call_cooldown_seconds: values.call_cooldown_seconds ?? "",
    campaign_default_concurrency: values.campaign_default_concurrency ?? "",
    campaign_max_concurrency: values.campaign_max_concurrency ?? "",
    campaign_pause_between_calls_seconds: values.campaign_pause_between_calls_seconds ?? "",
  };
}

export function SettingsForm({
  initial,
  onSaved,
}: {
  initial: DashboardSettings;
  onSaved: () => void;
}) {
  // Kein Reset-Effekt: die Elternkomponente vergibt bei jedem Neuladen der
  // Daten einen neuen `key` (siehe page.tsx), wodurch diese Komponente
  // frisch montiert wird und direkt mit den aktuellen Werten startet.
  const [form, setForm] = useState<FormState>(() => toFormState(initial.values));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function set<K extends keyof FormState>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.put("/api/settings", { values: form });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <div className="dv-eyebrow mb-3">Dario</div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label>Agent-Name</Label>
            <Input value={form.agent_name} onChange={(e) => set("agent_name", e.target.value)} />
          </div>
          <div>
            <Label>Firma</Label>
            <Input value={form.company_name} onChange={(e) => set("company_name", e.target.value)} />
          </div>
          <div>
            <Label>Standort</Label>
            <Input
              value={form.company_location}
              onChange={(e) => set("company_location", e.target.value)}
            />
          </div>
        </div>
      </div>

      <div>
        <div className="dv-eyebrow mb-3">Anrufe</div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label>Cooldown (s)</Label>
            <Input
              type="number"
              min={0}
              value={form.call_cooldown_seconds}
              onChange={(e) => set("call_cooldown_seconds", e.target.value)}
            />
          </div>
          <div>
            <Label>Wartezeit (s)</Label>
            <Input
              type="number"
              min={0}
              value={form.wait_timeout_seconds}
              onChange={(e) => set("wait_timeout_seconds", e.target.value)}
            />
          </div>
          <div>
            <Label>Stille-Timeout (s)</Label>
            <Input
              type="number"
              min={0}
              value={form.silence_timeout_seconds}
              onChange={(e) => set("silence_timeout_seconds", e.target.value)}
            />
          </div>
        </div>
      </div>

      <div>
        <div className="dv-eyebrow mb-3">Kampagnen</div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <Label>Standard-Parallelität</Label>
            <Input
              type="number"
              min={1}
              max={10}
              value={form.campaign_default_concurrency}
              onChange={(e) => set("campaign_default_concurrency", e.target.value)}
            />
          </div>
          <div>
            <Label>Maximale Parallelität</Label>
            <Input
              type="number"
              min={1}
              max={10}
              value={form.campaign_max_concurrency}
              onChange={(e) => set("campaign_max_concurrency", e.target.value)}
            />
          </div>
          <div>
            <Label>Pause zwischen Anrufen (s)</Label>
            <Input
              type="number"
              min={0}
              value={form.campaign_pause_between_calls_seconds}
              onChange={(e) => set("campaign_pause_between_calls_seconds", e.target.value)}
            />
          </div>
        </div>
      </div>

      {error && <p className="text-sm text-dv-danger">{error}</p>}
      {saved && <p className="text-sm text-dv-success">Gespeichert — gilt für alle neuen Anrufe.</p>}
      <Button disabled={saving} onClick={handleSave}>
        {saving ? "Speichert..." : "Speichern"}
      </Button>
    </div>
  );
}
