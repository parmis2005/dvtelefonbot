"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/swr";
import { api, ApiError } from "@/lib/api";
import type { VoiceProfile } from "@/lib/types";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { VoiceCard } from "./VoiceCard";
import { VoiceUploadModal } from "./VoiceUploadModal";

const DEFAULT_TEXT =
  "Guten Tag, hier ist Dario von Digital Vision. Ich melde mich kurz zu Ihrem Online-Auftritt.";

export default function StimmePage() {
  const { data: voices, mutate } = useSWR<VoiceProfile[]>("/api/voices", fetcher);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [testText, setTestText] = useState(DEFAULT_TEXT);
  const [generating, setGenerating] = useState(false);
  const [testAudioUrl, setTestAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeVoice = voices?.find((v) => v.is_active);

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
    <div>
      <PageHeader
        title="Stimme"
        subtitle="Referenzstimmen verwalten — keine künstlichen Pitch-/Tempo-Effekte, nur natürliches Voice-Cloning."
        actions={<Button onClick={() => setUploadOpen(true)}>+ Stimme hochladen</Button>}
      />

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
          <Button disabled={!activeVoice || generating} onClick={generateTest}>
            {generating ? "Generiert..." : "Audio generieren"}
          </Button>
        </CardContent>
      </Card>

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
