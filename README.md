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

Mehrsprachiges Modell herunterladen (Standard: `ggml-medium.bin`, ~1.5GB) nach
`models/whisper/`:

```bash
curl -L -o models/whisper/ggml-medium.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin
```

`.env`: `WHISPER_MODEL_PATH=./models/whisper/ggml-medium.bin`. `medium` statt
`small` ist bewusst der Standard: bei echten Telefonanrufen (8kHz, verlustbehaftetes
G.711 mu-law) erkennt `small` z.B. diktierte E-Mail-Adressen unzuverlaessig
(kein "@" im Ergebnis), `medium` deutlich zuverlaessiger - siehe CLAUDE.md
"Grenzen der aktuellen Version". Fuer schnellere, aber ungenauere Antworten
alternativ `ggml-small.bin` (~488MB).

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

## 10. Backend + einfaches Dashboard oeffnen

```bash
uvicorn app.main:app --reload
```

Einfaches, serverseitig gerendertes Dashboard (Jinja2, `dashboard/routes.py`):
http://127.0.0.1:8000/
API-Dokumentation (automatisch generiert): http://127.0.0.1:8000/docs

Fuer den taeglichen Betrieb (Kampagnen, Kontakte, Live-Anrufe, Prompt/Stimmen-
Verwaltung, Telefonie-Status, Sperrliste, Einstellungen) siehe stattdessen
**Abschnitt 17 (DVTelefonbot Dashboard)** - das vollstaendige Next.js-
Kontrollzentrum. Beide laufen gegen dasselbe Backend/dieselbe Datenbank.

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

## 15. Twilio verbinden (Alternative zu Asterisk)

Twilio Programmable Voice ist eine zweite, unabhaengige Telefonie-Anbindung
(`phone/twilio_voice.py`, `phone/twilio_media_handler.py`, `api/twilio.py`) -
kein SIP-Trunk/PBX-Setup noetig, dafuer ist ein oeffentlich erreichbarer
Server Pflicht (Twilio muss deinen Rechner uebers Internet erreichen).
Nutzt exakt dieselbe Dario-Engine wie Asterisk/Text-/Voice-Test.

**1. `.env` befuellen** (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_CALLER_ID` = deine verifizierte Twilio-Nummer, `TWILIO_TEST_NUMBER`).

**2. Server starten:**

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 30 --ws-ping-timeout 120
```

Alternativ, wenn Dashboard und Backend gemeinsam laufen sollen:

```bash
npm run dashboard
```

Die laengeren Ping-Timeouts sind bewusst: Chatterbox braucht auf CPU pro
Antwort ca. 15-45s reine Generierungszeit; mit den Standard-Timeouts (20s)
wertet die WebSocket-Verbindung das faelschlich als tot und trennt mitten in
Darios Antwort (siehe CLAUDE.md "Grenzen der aktuellen Version"). Mit
`TTS_PROVIDER=local_piper` sind die Standard-Timeouts unproblematisch.

**3. Oeffentlichen Tunnel starten** (zweites Terminal):

```bash
ngrok http 8000
```

Einmalig einen kostenlosen ngrok-Account samt Authtoken einrichten
(`ngrok config add-authtoken <dein-token>`, siehe https://dashboard.ngrok.com).
Die angezeigte `https://....ngrok-free.app`-URL (ohne abschliessenden Slash)
in `.env` als `TWILIO_PUBLIC_BASE_URL` eintragen. Bei jedem Neustart von
`ngrok http` aendert sich die URL (kostenloser Plan) - `.env` entsprechend
aktualisieren.

**4. Testanruf vorbereiten und ausloesen** (drittes Terminal):

```bash
npm run dev
```

Prueft Zugangsdaten und Erreichbarkeit des Webhooks, zeigt eine
Zusammenfassung und fragt explizit `Jetzt wirklich anrufen? Tippe 'ja' zum
Bestaetigen:` - erst nach Eingabe von `ja` wird der echte, kostenpflichtige
Anruf ausgeloest. Sobald abgenommen wird, verbindet Twilio den Call an
Darios Media-Stream-WebSocket (`/twilio/media-stream`) - STT, Conversation
Engine und TTS laufen dann in Echtzeit genau wie im lokalen Voice-Test.

Call-Status, Transkript und Zusammenfassung landen wie gewohnt in der
Datenbank/im Dashboard (`services/call_service.py`,
`services/transcript_service.py`, `services/summary_service.py`).

**Wichtig vor JEDEM echten Anruf:** Terminal 1 (`uvicorn`) UND Terminal 2
(`ngrok`) muessen GLEICHZEITIG laufen, und die `TWILIO_PUBLIC_BASE_URL` in
`.env` muss exakt der aktuell angezeigten ngrok-URL entsprechen (bei jedem
`ngrok http`-Neustart aendert sie sich). Ein Anruf, der zwar klingelt und
angenommen wird, aber sofort danach mit einer Fehleransage abbricht, bedeutet
fast immer: einer der beiden Prozesse lief zu diesem Zeitpunkt nicht (bzw.
die URL ist veraltet) - Twilio meldet das als Fehler 11200 ("Got HTTP 502
response"), siehe CLAUDE.md. Vor einem Testanruf pruefen:

```bash
curl -s $(grep TWILIO_PUBLIC_BASE_URL .env | cut -d= -f2)/api/health
```

Liefert das `{"status":"ok",...}` zurueck, ist der Pfad bereit. Dasselbe
zeigt auch das DVTelefonbot Dashboard live an: Seite **Telefonie** ->
"Öffentliche URL" (`api/telephony.py::telephony_status`, Feld
`public_base_url_reachable`) - ist der Tunnel/das Backend nicht erreichbar,
blockiert das Dashboard einen Testanruf jetzt von sich aus mit einer
klaren Fehlermeldung, statt den Kunden umsonst klingeln zu lassen.

## 16. Fehlerdiagnose

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
| `npm run dev`: "TWILIO_PUBLIC_BASE_URL fehlt" | Tunnel noch nicht gestartet/eingetragen | Schritt 15.3 (ngrok), URL ohne abschliessenden Slash in `.env` |
| `npm run dev`: Webhook "nicht erreichbar" (Warnung) | `uvicorn` oder `ngrok` laeuft nicht/ist abgestuerzt | Beide Terminals pruefen; Warnung blockiert den Anruf nicht, macht ihn aber sinnlos |
| Twilio-Anruf klingelt, aber Dario bleibt stumm/Verbindung bricht ab | WebSocket-Ping-Timeout waehrend langer Chatterbox-Generierung | `--ws-ping-interval`/`--ws-ping-timeout` wie in Schritt 15.2 setzen, oder testweise `TTS_PROVIDER=local_piper` |
| `403 Ungueltige Twilio-Signatur` auf `/twilio/voice` oder `/twilio/status` | Request kam nicht wirklich von Twilio (oder `TWILIO_PUBLIC_BASE_URL` stimmt nicht mit der tatsaechlich aufgerufenen URL ueberein) | `.env`-URL exakt mit der aktuellen ngrok-URL abgleichen |

Bei allen anderen Problemen: Logs in `logs/dario.log` (strukturiert, JSON)
sowie Konsolenausgabe pruefen. Telefonnummern werden in Logs automatisch
maskiert (`core/logging.py`).

## 17. DVTelefonbot Dashboard (Next.js Frontend)

Vollstaendiges Kontrollzentrum fuer den taeglichen Betrieb - Next.js +
TypeScript, im selben Repository unter `frontend/` (bewusst kein zweites
Repo). Baut ausschliesslich auf dem bestehenden Backend/den bestehenden
Provider-Pattern auf (Twilio-Anruf-Pfad, Conversation Engine, STT/TTS,
Datenbank) - keine zweite, vereinfachte Version von Dario.

**Funktionsumfang:** Uebersicht (Systemstatus, Kennzahlen), Kampagnen
(Sammelanrufe mit bis zu 10 parallelen, unabhaengigen Gespraechen, Pause/
Fortsetzen/Stoppen), Kontakte (CRUD, CSV-Import mit Vorschau + automatischer
Spaltenerkennung), Live-Anrufe (WebSocket-Live-Status), Anrufhistorie +
Transkript-Ansicht, Rueckrufe, Dario-Status, Prompt-Editor mit automatischer
Versionierung, Stimmenverwaltung (WAV-Upload, Test, Aktivierung - kein
Pitch-/Time-Stretching), Telefonie-Status + Testanruf, Sperrliste
(serverseitig vor jedem Anruf erzwungen), Einstellungen.

**Design:** eigenes, aus `https://www.digitalvision.site/` abgeleitetes
Design-System (Typografie Space Grotesk + Inter, Radius-/Schatten-/
Akzentfarben-Sprache), als CSS-Custom-Properties in
`frontend/src/app/globals.css` (`--dv-*`) definiert und per Tailwind-`@theme`
als Utility-Klassen (`bg-dv-surface`, `rounded-dv-md`, ...) nutzbar. Bewusst
HELL statt der dunklen Optik der Marketing-Seite (siehe Auftrag), aber mit
identischer Marken-DNA.

**Auth:** einzelner Admin-Account (`.env`: `DASHBOARD_USERNAME`,
`DASHBOARD_PASSWORD`), serverseitige In-Memory-Sessions (`core/auth.py`),
httpOnly-Cookie. Da das Frontend das Backend cross-origin anspricht, gibt es
bewusst KEIN serverseitiges Next.js-`proxy.ts` fuer die Zugriffskontrolle
(das Session-Cookie ist fuer die Backend-Origin gesetzt und fuer den
Next.js-Server gar nicht sichtbar) - die Durchsetzung passiert ausschliesslich
im Backend (`core/auth.py::require_auth`), das Frontend leitet bei 401 nur
sauber zu `/login` weiter.

**Starten (lokal):**

```bash
# Backend + Dashboard gemeinsam starten (Projekt-Root)
npm run dashboard

# Nur das Frontend separat starten (falls Backend schon laeuft)
cd frontend
npm install   # einmalig
cp .env.example .env.local   # einmalig, Default passt fuer lokale Entwicklung
npm run dev
```

Im Projekt-Root ist `npm run dev` bewusst NICHT das Dashboard, sondern der
bestaetigungspflichtige echte Twilio-Testanruf. Erst wenn im Prompt exakt
`ja` eingegeben wird, wird ein kostenpflichtiger Anruf ausgeloest.

Dashboard: http://localhost:3000/ (leitet zu `/login`, falls nicht
angemeldet). Zugangsdaten stehen in der lokalen `.env` des Backends
(`DASHBOARD_USERNAME`/`DASHBOARD_PASSWORD`).

**Wichtig - `localhost` statt `127.0.0.1` verwenden:** `frontend/.env.local`
muss `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` sein (nicht
`http://127.0.0.1:8000`), sobald das Dashboard selbst unter `localhost:3000`
aufgerufen wird - Browser behandeln `localhost` und `127.0.0.1` als
unterschiedliche SITES (nicht nur unterschiedliche Origins). Das
Session-Cookie ist `SameSite=Lax` (siehe `core/auth.py`), und genau dieses
Attribut wird bei Cross-Site-Fetches vom Browser ignoriert - der Login sieht
dann scheinbar erfolgreich aus (Set-Cookie kommt an), aber jede folgende
Anfrage schickt das Cookie nicht mehr mit, wodurch man nie im Dashboard
landet ("Anmelden tut nichts"). `.env.example` hat bereits den richtigen
Default; nach einer Aenderung an `NEXT_PUBLIC_*`-Variablen den Dev-Server neu
starten (Next.js baut sie nur beim Start ein, nicht live) und bei Bedarf
`frontend/.next/` loeschen, falls Turbopack einen alten Wert zwischenspeichert.

**Deployment:** Frontend fuer Vercel vorbereitet (`NEXT_PUBLIC_API_BASE_URL`
als Vercel-Umgebungsvariable auf die oeffentliche Backend-URL setzen). Das
Backend bleibt bewusst ein separater, dauerhaft laufender Server (z.B. VPS) -
**nicht** auf Vercel, da die langlebigen Twilio-Media-Stream-WebSockets
(`api/twilio.py`) nicht durch Vercel-Serverless-Functions laufen koennen.
Sobald Frontend und Backend auf getrennten HTTPS-Domains laufen, muessen in
der Backend-`.env` `DASHBOARD_COOKIE_SECURE=true` und
`DASHBOARD_COOKIE_SAMESITE=none` gesetzt werden (siehe `.env.example`),
sonst verwirft der Browser das Cross-Origin-Session-Cookie.

**Live-Status:** `api/live_status.py` liefert aktive Anrufe ueber eine
WebSocket (`/ws/live-status`), die serverseitig alle 1.5s die Datenbank
abfragt - kein echtes Event-Pub/Sub aus der Media-Stream-Session heraus (das
haette den bereits verifizierten Twilio-Audio-Pfad angefasst), aber fuer eine
Status-Anzeige (nicht die Audio-Echtzeitschleife selbst) ausreichend "live".

**Alle Einstellungen echt verdrahtet:** Agent-Name/Firma/Standort sowie
Anruf-Cooldown/Wartezeit/Stille-Timeout und die Kampagnen-Parallelitaet
werden ueber `services/effective_settings.py` gelesen und wirken auf JEDEN
neuen Call-Start (Einzelanruf, Testanruf, Kampagne) - ohne Backend-Neustart,
siehe CLAUDE.md fuer die technischen Details. Dabei wurde auch die bis dahin
unverdrahtete "Sind Sie noch da?"-Logik bei abgelaufener Wartezeit fertig
gebaut (`agent/dario.py::Dario.check_wait_timeout`).

**Ehrlich offene Punkte (Stand dieser Version):**
- Kein automatisierter Browser-Test (kein Headless-Browser/Playwright in
  dieser Umgebung verfuegbar) - verifiziert wurden `npm run build`,
  `npm run lint` (beide fehlerfrei), 94 Backend-Tests per `pytest`
  (u.a. `tests/test_api_dashboard.py`, `tests/test_campaign_manager.py`,
  `tests/test_effective_settings.py`, `tests/test_voices_api.py`,
  `tests/test_telephony_api.py`, `tests/test_calls_api.py`, echte FastAPI-App,
  Fake-Twilio-Provider statt echter Anrufe), sowie mehrere manuelle
  End-to-End-Rauchtests per `curl` gegen das echte laufende Backend (Login,
  Session-Cookie, geschuetzte Routen, automatisches Seeding von
  Prompt-Version/Stimme aus der bestehenden Produktionskonfiguration,
  Einstellungen-Rundlauf inkl. Zuruecksetzen auf die Produktionswerte danach).
  Ein Klick-Durchlauf im echten Browser vor dem produktiven Einsatz wird
  empfohlen.
- CSV-Import/Sammelanruf-Auswahl/Do-Not-Call/Kampagnen-Engine/Stimmen-
  Verwaltung/Telefonie-Testanruf sind ueber `tests/test_api_dashboard.py`,
  `tests/test_campaign_manager.py`, `tests/test_voices_api.py` und
  `tests/test_telephony_api.py` end-to-end gegen die echte FastAPI-App
  getestet (mit einem Fake-Twilio-Provider statt echter Anrufe).
