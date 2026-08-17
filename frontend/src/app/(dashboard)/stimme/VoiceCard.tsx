"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { VoiceProfile } from "@/lib/types";
import { Card, CardContent } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export function VoiceCard({
  voice,
  onChanged,
}: {
  voice: VoiceProfile;
  onChanged: () => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(voice.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  async function activate() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/voices/${voice.id}/activate`);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Aktivieren fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  async function saveRename() {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/voices/${voice.id}`, { name });
      setRenaming(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Umbenennen fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirm(`"${voice.name}" wirklich löschen?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/api/voices/${voice.id}`);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Löschen fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  async function listen() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.post<Blob>(`/api/voices/${voice.id}/test`);
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      setAudioUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Wiedergabe fehlgeschlagen.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <div className="mb-2 flex items-start justify-between">
          {renaming ? (
            <Input value={name} onChange={(e) => setName(e.target.value)} className="max-w-[70%]" />
          ) : (
            <div className="font-display text-base font-semibold text-dv-text-primary">
              {voice.name}
            </div>
          )}
          <div className="flex gap-1">
            {voice.is_active && <Badge tone="success">Aktiv</Badge>}
            {voice.is_builtin && <Badge tone="neutral">Standard</Badge>}
          </div>
        </div>

        <p className="text-xs text-dv-text-muted">
          exaggeration {voice.exaggeration} · cfg {voice.cfg_weight} · temp {voice.temperature}
        </p>

        {audioUrl && (
          <audio controls autoPlay src={audioUrl} className="mt-3 w-full">
            <track kind="captions" />
          </audio>
        )}

        {error && <p className="mt-2 text-sm text-dv-danger">{error}</p>}

        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" disabled={busy} onClick={listen}>
            ▶ Anhören
          </Button>
          {!voice.is_active && (
            <Button size="sm" disabled={busy} onClick={activate}>
              Als Dario-Stimme verwenden
            </Button>
          )}
          {renaming ? (
            <Button size="sm" variant="secondary" disabled={busy} onClick={saveRename}>
              Speichern
            </Button>
          ) : (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => setRenaming(true)}>
              Umbenennen
            </Button>
          )}
          {!voice.is_builtin && (
            <Button size="sm" variant="ghost" disabled={busy} onClick={remove}>
              Löschen
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
