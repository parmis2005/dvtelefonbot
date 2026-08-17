"use client";

import { FormEvent, useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { DoNotCallEntry } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

export default function SperrlistePage() {
  const { data: entries, mutate } = useSWR<DoNotCallEntry[]>("/api/do-not-call", fetcher);
  const [number, setNumber] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/api/do-not-call", { telefonnummer: number, reason: reason || undefined });
      setNumber("");
      setReason("");
      mutate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Hinzufügen fehlgeschlagen.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRemove(phone: string) {
    if (!confirm(`Sperre für ${phone} wirklich aufheben?`)) return;
    try {
      await api.delete(`/api/do-not-call/${encodeURIComponent(phone)}`);
      mutate();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Entfernen fehlgeschlagen.");
    }
  }

  return (
    <div>
      <PageHeader
        title="Sperrliste"
        subtitle="Gesperrte Nummern können technisch nicht angerufen werden — geprüft vor jedem Anruf im Backend."
      />

      <Card className="mb-6 p-6">
        <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[200px]">
            <label className="mb-1.5 block text-sm font-medium text-dv-text-secondary">
              Telefonnummer
            </label>
            <Input value={number} onChange={(e) => setNumber(e.target.value)} placeholder="+49..." required />
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="mb-1.5 block text-sm font-medium text-dv-text-secondary">Grund</label>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Optional" />
          </div>
          <Button type="submit" disabled={submitting}>
            Sperren
          </Button>
        </form>
        {error && <p className="mt-2 text-sm text-dv-danger">{error}</p>}
      </Card>

      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-dv-border-subtle text-xs text-dv-text-muted">
            <tr>
              <th className="px-4 py-3">Telefonnummer</th>
              <th className="px-4 py-3">Grund</th>
              <th className="px-4 py-3">Gesperrt am</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {entries?.map((entry) => (
              <tr key={entry.id} className="border-b border-dv-border-subtle last:border-0">
                <td className="px-4 py-3 font-medium text-dv-text-primary">{entry.telefonnummer}</td>
                <td className="px-4 py-3 text-dv-text-secondary">{entry.reason ?? "–"}</td>
                <td className="px-4 py-3 text-dv-text-secondary">
                  {new Date(entry.created_at).toLocaleDateString("de-DE")}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    className="text-xs font-medium text-dv-danger hover:underline"
                    onClick={() => handleRemove(entry.telefonnummer)}
                  >
                    Entsperren
                  </button>
                </td>
              </tr>
            ))}
            {(!entries || entries.length === 0) && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-dv-text-muted">
                  Keine gesperrten Nummern.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
