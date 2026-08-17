"use client";

import { DragEvent, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { api, ApiError } from "@/lib/api";
import type { CsvPreview } from "@/lib/types";

export function CsvImportModal({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  function reset() {
    setPreview(null);
    setError(null);
    setResult(null);
  }

  async function handleFile(file: File) {
    setError(null);
    setLoading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const data = await api.postForm<CsvPreview>("/api/leads/import/preview", form);
      setPreview(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Vorschau fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!preview) return;
    setLoading(true);
    setError(null);
    try {
      const validRows = preview.rows.filter((r) => r.valid).map((r) => r.data);
      const res = await api.post<{ created_count: number; errors: string[] }>(
        "/api/leads/import/confirm",
        validRows
      );
      setResult(`${res.created_count} Kontakt(e) importiert.`);
      onImported();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Import fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function handleClose() {
    reset();
    onClose();
  }

  return (
    <Modal open={open} onClose={handleClose} title="Kontakte per CSV importieren">
      {!preview && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`flex flex-col items-center justify-center rounded-dv-md border-2 border-dashed p-10 text-center transition-colors ${
            dragOver ? "border-dv-accent bg-dv-accent-soft" : "border-dv-border"
          }`}
        >
          <p className="text-sm text-dv-text-secondary">
            CSV-Datei hierher ziehen oder auswählen
          </p>
          <p className="mt-1 text-xs text-dv-text-muted">
            Spalten werden automatisch erkannt (Firma, Telefon, E-Mail, ...)
          </p>
          <label className="mt-4">
            <span className="cursor-pointer rounded-dv-sm bg-dv-accent px-4 py-2 text-sm font-medium text-white hover:bg-dv-accent-hover">
              Datei auswählen
            </span>
            <input
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
          </label>
          {loading && <p className="mt-3 text-xs text-dv-text-muted">Wird analysiert...</p>}
          {error && <p className="mt-3 text-sm text-dv-danger">{error}</p>}
        </div>
      )}

      {preview && !result && (
        <div>
          <div className="mb-4 flex gap-2">
            <Badge tone="success">{preview.valid_count} gültig</Badge>
            <Badge tone="danger">{preview.invalid_count} ungültig</Badge>
            <Badge tone="neutral">{preview.total} gesamt</Badge>
          </div>
          <div className="max-h-72 overflow-auto rounded-dv-sm border border-dv-border-subtle">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-dv-surface-secondary text-xs text-dv-text-muted">
                <tr>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2">Unternehmen</th>
                  <th className="px-3 py-2">Telefonnummer</th>
                  <th className="px-3 py-2">Fehler</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, i) => (
                  <tr key={i} className="border-t border-dv-border-subtle">
                    <td className="px-3 py-2">
                      <Badge tone={row.valid ? "success" : "danger"}>
                        {row.valid ? "OK" : "Fehler"}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">{row.data.unternehmen || "–"}</td>
                    <td className="px-3 py-2">{row.data.telefonnummer || "–"}</td>
                    <td className="px-3 py-2 text-xs text-dv-danger">{row.errors.join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {error && <p className="mt-3 text-sm text-dv-danger">{error}</p>}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={reset}>
              Andere Datei
            </Button>
            <Button onClick={handleConfirm} disabled={loading || preview.valid_count === 0}>
              {loading ? "Importiert..." : `${preview.valid_count} Kontakt(e) importieren`}
            </Button>
          </div>
        </div>
      )}

      {result && (
        <div className="text-center">
          <p className="text-sm font-medium text-dv-success">{result}</p>
          <Button className="mt-4" onClick={handleClose}>
            Fertig
          </Button>
        </div>
      )}
    </Modal>
  );
}
