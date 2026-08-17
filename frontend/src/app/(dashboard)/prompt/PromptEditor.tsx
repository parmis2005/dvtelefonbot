"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";

export function PromptEditor({
  initialContent,
  onSaved,
}: {
  initialContent: string;
  onSaved: () => void;
}) {
  // Kein useEffect fuer den Reset: die Elternkomponente vergibt einen neuen
  // `key` (Version-ID), sobald sich die aktive Version aendert - dadurch
  // wird dieser Editor frisch montiert und `draft` startet direkt mit dem
  // korrekten Inhalt (React-Empfehlung statt useEffect+setState).
  const [draft, setDraft] = useState(initialContent);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = draft !== initialContent;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.post("/api/prompt-versions", { content: draft, activate: true });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <Textarea
        rows={20}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        className="font-mono text-sm"
      />
      {error && <p className="mt-2 text-sm text-dv-danger">{error}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" disabled={!dirty} onClick={() => setDraft(initialContent)}>
          Verwerfen
        </Button>
        <Button disabled={!dirty || saving} onClick={handleSave}>
          {saving ? "Speichert..." : "Speichern"}
        </Button>
      </div>
    </div>
  );
}
