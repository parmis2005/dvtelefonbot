"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { TelephonyStatus, VoiceProfile } from "@/lib/types";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";

export function TestCallModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: telephony } = useSWR<TelephonyStatus>("/api/telephony/status", fetcher);
  const { data: voices } = useSWR<VoiceProfile[]>("/api/voices", fetcher);
  const [number, setNumber] = useState("");
  const [step, setStep] = useState<"input" | "confirm" | "done">("input");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const activeVoice = voices?.find((v) => v.is_active);

  function handleClose() {
    setStep("input");
    setError(null);
    setNumber("");
    onClose();
  }

  async function handleConfirmedTestCall() {
    setLoading(true);
    setError(null);
    try {
      await api.post("/api/telephony/test-call", { to_number: number });
      setStep("done");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Testanruf fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Testanruf">
      {step === "input" && (
        <div className="space-y-4">
          <div>
            <Label>Zielnummer</Label>
            <Input
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              placeholder="+49..."
              autoFocus
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={handleClose}>
              Abbrechen
            </Button>
            <Button disabled={!number} onClick={() => setStep("confirm")}>
              Weiter
            </Button>
          </div>
        </div>
      )}

      {step === "confirm" && (
        <div className="space-y-4">
          <div className="space-y-2 text-sm">
            <Row label="Von" value={telephony?.caller_id ?? "Nicht konfiguriert"} />
            <Row label="An" value={number} />
            <Row label="Agent" value="Dario" />
            <Row label="Stimme" value={activeVoice?.name ?? "Standard"} />
          </div>
          <p className="text-xs text-dv-text-muted">
            Dies ist ein ECHTER, kostenpflichtiger Anruf über die vollständige Dario-Gesprächs-Engine.
          </p>
          {error && <p className="text-sm text-dv-danger">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={handleClose}>
              Abbrechen
            </Button>
            <Button onClick={handleConfirmedTestCall} disabled={loading}>
              {loading ? "Startet..." : "Jetzt testen"}
            </Button>
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="text-center">
          <p className="text-sm font-medium text-dv-success">Testanruf ausgelöst.</p>
          <Button className="mt-4" onClick={handleClose}>
            Fertig
          </Button>
        </div>
      )}
    </Modal>
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
