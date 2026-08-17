"use client";

import { FormEvent, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Input, Label, Textarea } from "@/components/ui/Input";
import { api, ApiError } from "@/lib/api";
import type { Lead } from "@/lib/types";

interface FormState {
  unternehmen: string;
  ansprechpartner: string;
  telefonnummer: string;
  email: string;
  branche: string;
  website_url: string;
  notizen: string;
  online_auftritt_geprueft: boolean;
  entwurf_vorhanden: boolean;
  entwurf_link: string;
}

function toFormState(lead: Lead | null): FormState {
  if (!lead) {
    return {
      unternehmen: "",
      ansprechpartner: "",
      telefonnummer: "",
      email: "",
      branche: "",
      website_url: "",
      notizen: "",
      online_auftritt_geprueft: false,
      entwurf_vorhanden: false,
      entwurf_link: "",
    };
  }
  return {
    unternehmen: lead.unternehmen,
    ansprechpartner: lead.ansprechpartner ?? "",
    telefonnummer: lead.telefonnummer,
    email: lead.email ?? "",
    branche: lead.branche ?? "",
    website_url: lead.website_url ?? "",
    notizen: lead.notizen ?? "",
    online_auftritt_geprueft: lead.online_auftritt_geprueft,
    entwurf_vorhanden: lead.entwurf_vorhanden,
    entwurf_link: lead.entwurf_link ?? "",
  };
}

export function LeadFormModal({
  open,
  onClose,
  onSaved,
  lead,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  lead: Lead | null;
}) {
  // Kein Reset-Effekt: die Elternkomponente gibt bei jedem Oeffnen einen
  // neuen `key` mit (siehe app/(dashboard)/kontakte/page.tsx), wodurch diese
  // Komponente frisch montiert wird und der Initialwert direkt aus `lead`
  // berechnet werden kann (React-Empfehlung fuer "State bei Prop-Wechsel
  // zuruecksetzen" statt useEffect+setState).
  const [form, setForm] = useState<FormState>(() => toFormState(lead));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      if (lead) {
        await api.patch(`/api/leads/${lead.id}`, form);
      } else {
        await api.post("/api/leads", form);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title={lead ? "Kontakt bearbeiten" : "Kontakt hinzufügen"}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label>Unternehmen *</Label>
            <Input
              required
              value={form.unternehmen}
              onChange={(e) => setForm({ ...form, unternehmen: e.target.value })}
            />
          </div>
          <div>
            <Label>Ansprechpartner</Label>
            <Input
              value={form.ansprechpartner}
              onChange={(e) => setForm({ ...form, ansprechpartner: e.target.value })}
            />
          </div>
          <div>
            <Label>Telefonnummer *</Label>
            <Input
              required
              value={form.telefonnummer}
              onChange={(e) => setForm({ ...form, telefonnummer: e.target.value })}
              placeholder="+49..."
            />
          </div>
          <div>
            <Label>E-Mail</Label>
            <Input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          <div>
            <Label>Branche</Label>
            <Input value={form.branche} onChange={(e) => setForm({ ...form, branche: e.target.value })} />
          </div>
          <div>
            <Label>Webseite</Label>
            <Input
              value={form.website_url}
              onChange={(e) => setForm({ ...form, website_url: e.target.value })}
            />
          </div>
        </div>

        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm text-dv-text-secondary">
            <input
              type="checkbox"
              checked={form.online_auftritt_geprueft}
              onChange={(e) => setForm({ ...form, online_auftritt_geprueft: e.target.checked })}
            />
            Online-Auftritt geprüft
          </label>
          <label className="flex items-center gap-2 text-sm text-dv-text-secondary">
            <input
              type="checkbox"
              checked={form.entwurf_vorhanden}
              onChange={(e) => setForm({ ...form, entwurf_vorhanden: e.target.checked })}
            />
            Entwurf vorhanden
          </label>
        </div>

        {form.entwurf_vorhanden && (
          <div>
            <Label>Entwurf-Link</Label>
            <Input
              value={form.entwurf_link}
              onChange={(e) => setForm({ ...form, entwurf_link: e.target.value })}
            />
          </div>
        )}

        <div>
          <Label>Notizen</Label>
          <Textarea
            rows={3}
            value={form.notizen}
            onChange={(e) => setForm({ ...form, notizen: e.target.value })}
          />
        </div>

        {error && <p className="text-sm text-dv-danger">{error}</p>}

        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Abbrechen
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "Speichert..." : "Speichern"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
