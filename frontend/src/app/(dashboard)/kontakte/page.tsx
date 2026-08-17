"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { useRouter } from "next/navigation";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { Lead } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import { LeadFormModal } from "./LeadFormModal";
import { CsvImportModal } from "./CsvImportModal";

const STATUS_TONE: Record<string, "neutral" | "accent" | "warm" | "danger" | "success" | "cyan"> = {
  NEW: "neutral",
  INTERESTED: "success",
  QUALIFIED: "success",
  DESIGN_REQUESTED: "accent",
  DESIGN_SENT: "accent",
  CALLBACK: "warm",
  FOLLOW_UP: "warm",
  NOT_INTERESTED: "danger",
  DO_NOT_CALL: "danger",
  NO_ANSWER: "neutral",
  BUSY: "neutral",
  GATEKEEPER: "neutral",
  CALLED: "cyan",
  HANDOFF_TO_MANAGEMENT: "cyan",
};

export default function KontaktePage() {
  const { data: leads, mutate } = useSWR<Lead[]>("/api/leads", fetcher);
  const router = useRouter();

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [formOpen, setFormOpen] = useState(false);
  const [editingLead, setEditingLead] = useState<Lead | null>(null);
  const [formKey, setFormKey] = useState(0);
  const [csvOpen, setCsvOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!leads) return [];
    const q = search.trim().toLowerCase();
    if (!q) return leads;
    return leads.filter(
      (l) =>
        l.unternehmen.toLowerCase().includes(q) ||
        (l.ansprechpartner ?? "").toLowerCase().includes(q) ||
        l.telefonnummer.includes(q)
    );
  }, [leads, search]);

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

  async function handleDelete(lead: Lead) {
    if (!confirm(`"${lead.unternehmen}" wirklich löschen?`)) return;
    try {
      await api.delete(`/api/leads/${lead.id}`);
      mutate();
    } catch (err) {
      alert(err instanceof ApiError ? err.message : "Löschen fehlgeschlagen.");
    }
  }

  function addSelectedToCampaign() {
    if (selected.size === 0) return;
    sessionStorage.setItem("dv-campaign-lead-ids", JSON.stringify(Array.from(selected)));
    router.push("/kampagnen?prefill=1");
  }

  return (
    <div>
      <PageHeader
        title="Kontakte"
        subtitle={`${leads?.length ?? 0} Kontakte`}
        actions={
          <>
            <Button variant="secondary" onClick={() => setCsvOpen(true)}>
              CSV importieren
            </Button>
            <Button
              onClick={() => {
                setEditingLead(null);
                setFormKey((k) => k + 1);
                setFormOpen(true);
              }}
            >
              + Kontakt
            </Button>
          </>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input
          placeholder="Suche nach Unternehmen, Ansprechpartner, Telefonnummer..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
        {selected.size > 0 && (
          <div className="flex items-center gap-2 rounded-dv-sm bg-dv-accent-soft px-3 py-1.5 text-sm text-dv-accent">
            {selected.size} ausgewählt
            <Button size="sm" onClick={addSelectedToCampaign}>
              Zur Kampagne hinzufügen
            </Button>
          </div>
        )}
      </div>

      <Card className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-dv-border-subtle text-xs text-dv-text-muted">
            <tr>
              <th className="px-4 py-3"></th>
              <th className="px-4 py-3">Unternehmen</th>
              <th className="px-4 py-3">Ansprechpartner</th>
              <th className="px-4 py-3">Telefonnummer</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Rückruf</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((lead) => (
              <tr key={lead.id} className="border-b border-dv-border-subtle last:border-0 hover:bg-dv-surface-hover">
                <td className="px-4 py-3">
                  <input
                    type="checkbox"
                    checked={selected.has(lead.id)}
                    onChange={() => toggle(lead.id)}
                  />
                </td>
                <td className="px-4 py-3 font-medium text-dv-text-primary">{lead.unternehmen}</td>
                <td className="px-4 py-3 text-dv-text-secondary">{lead.ansprechpartner || "–"}</td>
                <td className="px-4 py-3 text-dv-text-secondary">{lead.telefonnummer}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-1">
                    <Badge tone={STATUS_TONE[lead.status] ?? "neutral"}>{lead.status}</Badge>
                    {lead.do_not_call && <Badge tone="danger">Gesperrt</Badge>}
                  </div>
                </td>
                <td className="px-4 py-3 text-dv-text-secondary">
                  {lead.callback_at ? new Date(lead.callback_at).toLocaleDateString("de-DE") : "–"}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    className="mr-2 text-xs font-medium text-dv-accent hover:underline"
                    onClick={() => {
                      setEditingLead(lead);
                      setFormKey((k) => k + 1);
                      setFormOpen(true);
                    }}
                  >
                    Bearbeiten
                  </button>
                  <button
                    className="text-xs font-medium text-dv-danger hover:underline"
                    onClick={() => handleDelete(lead)}
                  >
                    Löschen
                  </button>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-dv-text-muted">
                  Keine Kontakte gefunden.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      <LeadFormModal
        key={formKey}
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={() => mutate()}
        lead={editingLead}
      />
      <CsvImportModal open={csvOpen} onClose={() => setCsvOpen(false)} onImported={() => mutate()} />
    </div>
  );
}
