"use client";

import { FormEvent, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Input, Label } from "@/components/ui/Input";
import { api, ApiError } from "@/lib/api";

export function VoiceUploadModal({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handleClose() {
    setName("");
    setFile(null);
    setError(null);
    onClose();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.postForm(`/api/voices/upload?name=${encodeURIComponent(name)}`, form);
      onUploaded();
      handleClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Modal open={open} onClose={handleClose} title="Neue Stimme hochladen">
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <Label>Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} required />
        </div>
        <div>
          <Label>WAV-Datei</Label>
          <input
            type="file"
            accept=".wav"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-dv-text-secondary"
            required
          />
        </div>
        {error && <p className="text-sm text-dv-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={handleClose}>
            Abbrechen
          </Button>
          <Button type="submit" disabled={loading || !file}>
            {loading ? "Lädt hoch..." : "Hochladen"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
