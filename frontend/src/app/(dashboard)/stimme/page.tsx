"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { DashboardSettings, VoiceProfile } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { VoiceCard } from "./VoiceCard";
import { VoiceUploadModal } from "./VoiceUploadModal";

const DEFAULT_TEXT =
  "Guten Tag, hier ist Dario von Digital Vision. Ich melde mich kurz zu Ihrem Online-Auftritt.";

function VoiceTestEditor({
  initialText,
  activeVoice,
  onSaved,
}: {
  initialText: string;
  activeVoice: VoiceProfile | undefined;
  onSaved: () => void;
}) {
  const [testText, setTestText] = useState(initialText);
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testAudioUrl, setTestAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dirty = testText !== initialText;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.put("/api/settings", { values: { voice_test_text: testText } });
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  async function generateTest() {
    if (!activeVoice) return;
    setGenerating(true);
    setError(null);
    try {
      const blob = await api.post<Blob>(`/api/voices/${activeVoice.id}/test?text=${encodeURIComponent(testText)}`);
      if (testAudioUrl) URL.revokeObjectURL(testAudioUrl);
      setTestAudioUrl(URL.createObjectURL(blob));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Audio-Generierung fehlgeschlagen.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <Card className="mb-6">
      <CardHeader>
        <CardTitle>Stimmtest</CardTitle>
      </CardHeader>
      <CardContent>
        <Textarea
          rows={3}
          value={testText}
          onChange={(e) => setTestText(e.target.value)}
          className="mb-3"
        />
        {error && <p className="mb-2 text-sm text-dv-danger">{error}</p>}
        {testAudioUrl && (
          <audio controls autoPlay src={testAudioUrl} className="mb-3 w-full">
            <track kind="captions" />
          </audio>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={!activeVoice || generating} onClick={generateTest}>
            {generating ? "Generiert..." : "Audio generieren"}
          </Button>
          <Button variant="secondary" disabled={!dirty || saving} onClick={() => setTestText(initialText)}>
            Verwerfen
          </Button>
          <Button disabled={!dirty || saving} onClick={handleSave}>
            {saving ? "Speichert..." : "Speichern"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function StimmePage() {
  const { data: voices, mutate } = useSWR<VoiceProfile[]>("/api/voices", fetcher);
  const { data: settings, mutate: mutateSettings } = useSWR<DashboardSettings>("/api/settings", fetcher);
  const [uploadOpen, setUploadOpen] = useState(false);

  const activeVoice = voices?.find((v) => v.is_active);
  const initialText = settings?.values.voice_test_text ?? DEFAULT_TEXT;

  return (
    <div>
      <PageHeader
        title="Stimme"
        subtitle="Referenzstimmen verwalten — keine künstlichen Pitch-/Tempo-Effekte, nur natürliches Voice-Cloning."
        actions={<Button onClick={() => setUploadOpen(true)}>+ Stimme hochladen</Button>}
      />

      <VoiceTestEditor
        key={initialText}
        initialText={initialText}
        activeVoice={activeVoice}
        onSaved={() => mutateSettings()}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {voices?.map((voice) => (
          <VoiceCard key={voice.id} voice={voice} onChanged={() => mutate()} />
        ))}
      </div>

      <VoiceUploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => mutate()}
      />
    </div>
  );
}
