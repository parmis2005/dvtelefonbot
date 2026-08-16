# Digital Vision Dario

Ein lokal-first KI-Telefonagent ("Dario") fuer **Digital Vision**
(Moenchengladbach). Dario fuehrt ausgehende Erstgespraeche mit potenziellen
Geschaeftskunden, weckt Interesse an einem moderneren Online-Auftritt, bietet
einen unverbindlichen Webseiten-Entwurf an und nimmt Kontaktdaten sowie
Rueckrufwuensche auf - ohne im ersten Gespraech einen Vertrag abzuschliessen.

Architektur, Business-Regeln und Sicherheitsleitplanken: siehe
[CLAUDE.md](CLAUDE.md).

## 1. Voraussetzungen

- macOS (getestet), Homebrew installiert (https://brew.sh)
- Python 3.12+
- Git

Optional, aber fuer die vollen Faehigkeiten empfohlen:
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (Speech-to-Text)
- [llama.cpp](https://github.com/ggerganov/llama.cpp) (lokales LLM, `llama-server`)
- [Chatterbox Multilingual](https://github.com/resemble-ai/chatterbox) (Text-to-Speech, Standard - natuerliche deutsche maennliche Stimme) oder [Piper](https://github.com/rhasspy/piper) (schnellere Alternative)
- [Asterisk](https://www.asterisk.org/) mit ARI (fuer echte Telefonanrufe)

Alle diese Schritte werden von `scripts/setup_mac.sh` interaktiv unterstuetzt.

## 2. Installation

```bash
git clone <dieses-repo>
cd digital-vision-dario
bash scripts/setup_mac.sh
```

Das Skript legt ein `.venv` an, installiert die Python-Abhaengigkeiten und
hilft bei der Installation der optionalen lokalen Tools. Es nimmt keine
gefaehrlichen Systemaenderungen ohne Rueckfrage vor.

Manuell (ohne Skript):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev,voice]"
```

## 3. `.env` konfigurieren

```bash
cp .env.example .env
```

Danach `.env` mit echten Werten befuellen (SMTP, Asterisk, WhatsApp,
Modellpfade). **`.env` niemals committen** - sie ist in `.gitignore`
ausgeschlossen. Ohne echte Zugangsdaten funktionieren Text-Test, Datenbank,
Dashboard und API vollstaendig; nur der jeweilige externe Versand/Anruf
schlaegt dann ehrlich fehl (siehe CLAUDE.md, Abschnitt "Grenzen").

Statische Geschaeftskonfiguration (Preise, Cooldowns, Firmendaten) steht in
`config.yaml` und muss in der Regel nicht angefasst werden.

## 4. Datenbank starten

Keine separate Datenbank-Installation noetig - SQLite wird automatisch beim
ersten Start angelegt (`data/dario.db`, siehe `DATABASE_URL` in `.env`).

```bash
python -c "import asyncio; from database.database import init_db; asyncio.run(init_db())"
```

(Dieser Schritt laeuft ausserdem automatisch beim Start von `app.chat_test`,
`app.local_voice_test` und `uvicorn app.main:app`.)

## 5. Lokales LLM installieren

```bash
brew install llama.cpp   # oder manueller Build, siehe scripts/setup_mac.sh
```

Ein deutschfaehiges, instruction-getuntes GGUF-Modell herunterladen (z.B. von
Hugging Face) und den Server starten:

```bash
llama-server -m ./models/llm/<dein-modell>.gguf --port 8080
```

`.env`: `LLAMA_SERVER_URL=http://127.0.0.1:8080`. Laeuft kein Server, faellt
Dario automatisch auf regelbasierte Template-Antworten zurueck (kein Absturz,
siehe `agent/conversation.py::_llm_or_fallback`).

## 6. Whisper installieren

```bash
brew install whisper-cpp   # stellt z.B. `whisper-cli` bereit
```

Mehrsprachiges Modell herunterladen (Standard: `ggml-small.bin`, guter
Kompromiss aus Tempo/Genauigkeit fuer Deutsch) nach `models/whisper/`:

```bash
curl -L -o models/whisper/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

`.env`: `WHISPER_MODEL_PATH=./models/whisper/ggml-small.bin`. Fuer hoehere
Genauigkeit (langsamer) alternativ `ggml-medium.bin`.

## 7. TTS installieren

Dario nutzt aktuell standardmaessig **Chatterbox Multilingual** (natuerlicher,
aber deutlich langsamer als Piper - Ergebnis mehrerer Stimm-Vergleichsrunden,
siehe `voice/tts/chatterbox_tts.py`). Piper bleibt als schnellere Alternative
verfuegbar.

**Chatterbox (Standard, `TTS_PROVIDER=chatterbox`):**

```bash
pip install -e ".[chatterbox]"   # ~2GB, zieht PyTorch + transformers nach
```

Optional eine eigene Referenzstimme klonen: WAV-Datei (>= 5s, sauberer
Einzelsprecher) nach `models/voice_reference/dario_reference.wav` legen und in
`.env` `CHATTERBOX_REFERENCE_AUDIO_PATH=./models/voice_reference/dario_reference.wav`
setzen. Wer diese Datei bereitstellt, muss die Rechte an der Stimme haben.
Ohne Referenz nutzt Chatterbox seine eingebaute Standardstimme. Laeuft bewusst
auf CPU (`CHATTERBOX_DEVICE=cpu`) - Apple-Silicon-MPS ist mit Chatterbox
aktuell inkompatibel. Modellgewichte laden beim ersten Start automatisch von
Hugging Face (~2GB).

**Piper (Alternative, `TTS_PROVIDER=local_piper`):**

```bash
pip install -e ".[voice]"   # enthaelt piper-tts
```

Deutsche maennliche Stimme (empfohlen: `de_DE-thorsten-high`) nach
`models/piper/` herunterladen. `.env`: `PIPER_MODEL_PATH=./models/piper/de_DE-thorsten-high.onnx`.

## 8. Text-Test starten

Funktioniert **ohne** Asterisk/Whisper/Piper - nutzt bei fehlendem LLM
automatisch die Template-Antworten:

```bash
source .venv/bin/activate
python -m app.chat_test --entwurf --geprueft
```

Optionen: `--lead-id <id>` (bestehenden Lead verwenden), `--entwurf`
(Test-Lead mit vorhandenem Entwurf), `--geprueft` (Test-Lead mit geprueftem
Online-Auftritt). Eingabe `exit` beendet den Test manuell.

## 9. Voice-Test starten

Benoetigt whisper.cpp (Schritt 6), die `voice`-Extras (`pip install -e ".[voice]"`,
bereits Teil von `setup_mac.sh`) sowie den in `TTS_PROVIDER` gewaehlten
TTS-Provider aus Schritt 7 (Standard: Chatterbox, Extra `chatterbox`):

```bash
python -m app.local_voice_test --entwurf --geprueft
```

Ablauf: Mac-Mikrofon -> whisper.cpp -> Dario Conversation Engine -> LLM ->
TTS-Provider -> Mac-Lautsprecher. Aufnahme endet automatisch bei erkannter
Stille (VAD, `voice/vad.py`). Mit Chatterbox dauert das erste Modell-Laden
ca. 10-15s, danach jede Antwort auf CPU nochmal ca. 25-30s Generierungszeit -
fuer diesen Test in Ordnung, aber (noch) nicht telefonietauglich (siehe
CLAUDE.md "Grenzen der aktuellen Version").

## 10. Dashboard oeffnen

```bash
uvicorn app.main:app --reload
```

Dashboard: http://127.0.0.1:8000/
API-Dokumentation (automatisch generiert): http://127.0.0.1:8000/docs

Leads importieren:

```bash
python -m scripts.import_leads_csv --file leads.csv
```

Erwartete CSV-Spalten: `unternehmen, ansprechpartner, telefonnummer, branche,
website_url, online_auftritt_geprueft, entwurf_vorhanden, entwurf_link,
email, notizen`.

## 11. Asterisk installieren

```bash
brew install asterisk
```

Asterisk-Konfigurationsverzeichnis typischerweise unter
`/opt/homebrew/etc/asterisk/`. ARI aktivieren in `ari.conf` (Vorlage:
`phone/sip.py::render_ari_conf`), z.B.:

```ini
[general]
enabled = yes
pretty = yes

[dario_ari]
type = user
password = <starkes-passwort>
read_only = no
```

In `http.conf` sicherstellen, dass der eingebaute HTTP-Server aktiv ist
(ARI laeuft darueber):

```ini
[general]
enabled = yes
bindaddr = 127.0.0.1
bindport = 8088
```

## 12. SIP konfigurieren

PJSIP-Trunk-Konfiguration generieren lassen (Beispiel, Werte anpassen):

```python
from phone.sip import render_pjsip_trunk_conf, render_extensions_conf
print(render_pjsip_trunk_conf("default_trunk", "sip.dein-provider.de", "sip_user", "sip_pass"))
print(render_extensions_conf("dario"))
```

Ergebnis in `pjsip.conf` bzw. `extensions.conf` einfuegen. `.env` entsprechend
befuellen: `ASTERISK_SIP_TRUNK`, `ASTERISK_USERNAME`, `ASTERISK_PASSWORD`,
`ASTERISK_CALLER_ID`.

## 13. Telefonnummer verbinden

SIP-Trunk-Zugangsdaten deines VoIP-/SIP-Providers in `pjsip.conf` (Schritt 12)
eintragen. Asterisk neu laden:

```bash
asterisk -rx "pjsip reload"
asterisk -rx "dialplan reload"
```

## 14. Ersten Testanruf durchfuehren

```bash
uvicorn app.main:app --reload
# In einem zweiten Terminal:
curl -X POST http://127.0.0.1:8000/api/calls \
  -H "Content-Type: application/json" \
  -d '{"lead_id": 1}'
```

Ohne laufenden/erreichbaren Asterisk-Server antwortet der Endpunkt ehrlich
mit `502` und einer Fehlermeldung - es wird nie ein erfolgreicher Call
vorgetaeuscht.

## 15. Fehlerdiagnose

| Symptom | Wahrscheinliche Ursache | Loesung |
|---|---|---|
| `python -m app.chat_test` bricht mit Importfehler ab | venv nicht aktiviert / Abhaengigkeiten fehlen | `source .venv/bin/activate && pip install -e ".[dev,voice]"` |
| `LocalLlamaProvider nicht erreichbar` im Log | `llama-server` laeuft nicht | Schritt 5 wiederholen, oder Template-Fallback akzeptieren |
| `WhisperBinaryNotFoundError` | `whisper-cli` nicht im PATH oder Modell fehlt | Schritt 6, `.env` Pfade pruefen |
| `PiperBinaryNotFoundError` | Piper nicht installiert oder Modell fehlt (nur bei `TTS_PROVIDER=local_piper`) | Schritt 7 |
| `ChatterboxUnavailableError` | Paket `chatterbox-tts` nicht installiert oder `CHATTERBOX_REFERENCE_AUDIO_PATH` zeigt auf fehlende Datei | `pip install -e ".[chatterbox]"`, `.env` Pfad pruefen |
| `local_voice_test` dauert beim ersten Satz sehr lange | Chatterbox laedt Modellgewichte + generiert auf CPU (~25-30s/Aeusserung normal) | Kein Fehler - siehe CLAUDE.md "Grenzen der aktuellen Version"; fuer schnellere Antworten `TTS_PROVIDER=local_piper` setzen |
| `502` bei `POST /api/calls` | Asterisk/ARI nicht erreichbar | Schritt 11-13 pruefen, `asterisk -rx "core show version"` |
| E-Mail wird nie als "gesendet" bestaetigt | SMTP-Zugangsdaten fehlen/falsch (`.env`) | `SMTP_*` Variablen pruefen; das ist bewusstes Verhalten (kein falscher Versand-Claim) |
| `pytest` findet `webrtcvad`-Importfehler | `pkg_resources` fehlt (neue `setuptools`-Version) | `pip install -e ".[voice]"` installiert automatisch `setuptools<81` |
| Anruf wird trotz "nicht mehr anrufen" erneut versucht | Sollte nicht vorkommen - Do-Not-Call ist persistent in DB | `tests/test_do_not_call.py` ausfuehren, Datenbank pruefen (`do_not_call` Tabelle) |

Bei allen anderen Problemen: Logs in `logs/dario.log` (strukturiert, JSON)
sowie Konsolenausgabe pruefen. Telefonnummern werden in Logs automatisch
maskiert (`core/logging.py`).
