"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import type { DashboardSettings } from "@/lib/types";

export function SettingsForm({
  initial,
  onSaved,
}: {
  initial: DashboardSettings;
  onSaved: () => void;
}) {
  const [defaultConcurrency, setDefaultConcurrency] = useState(
    initial.values.campaign_default_concurrency
  );
  const [maxConcurrency, setMaxConcurrency] = useState(initial.values.campaign_max_concurrency);
  const [pauseBetween, setPauseBetween] = useState(
    initial.values.campaign_pause_between_calls_seconds
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.put("/api/settings", {
        values: {
          campaign_default_concurrency: defaultConcurrency,
          campaign_max_concurrency: maxConcurrency,
          campaign_pause_between_calls_seconds: pauseBetween,
        },
      });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label>Standard-Parallelität</Label>
          <Input
            type="number"
            min={1}
            max={10}
            value={defaultConcurrency}
            onChange={(e) => setDefaultConcurrency(e.target.value)}
          />
        </div>
        <div>
          <Label>Maximale Parallelität</Label>
          <Input
            type="number"
            min={1}
            max={10}
            value={maxConcurrency}
            onChange={(e) => setMaxConcurrency(e.target.value)}
          />
        </div>
        <div>
          <Label>Pause zwischen Anrufen (s)</Label>
          <Input
            type="number"
            min={0}
            value={pauseBetween}
            onChange={(e) => setPauseBetween(e.target.value)}
          />
        </div>
      </div>
      {error && <p className="text-sm text-dv-danger">{error}</p>}
      {saved && <p className="text-sm text-dv-success">Gespeichert.</p>}
      <Button disabled={saving} onClick={handleSave}>
        {saving ? "Speichert..." : "Speichern"}
      </Button>
    </div>
  );
}
