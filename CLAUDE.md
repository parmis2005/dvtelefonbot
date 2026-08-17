# CLAUDE.md - Digital Vision Dario

Dauerhafte Projektregeln fuer die Arbeit an diesem Repository. Diese Datei ist
die massgebliche Referenz - bei Konflikten mit Kommentaren im Code oder alten
Notizen gilt diese Datei.

## Projektname

**Digital Vision Dario** - ein KI-Telefonagent ("Dario") fuer **Digital
Vision**, ein Unternehmen aus **Moenchengladbach**, das Webseiten, SEO,
Verwaltungssysteme und Dashboards fuer Geschaeftskunden erstellt.

Ziel: ein von Digital Vision unabhaengig betreibbarer, lokal-first
Telefonagent - langfristig ohne Abhaengigkeit von Plattformen wie ElevenLabs
Agents.

## Architektur

```
Telefonnetz/SIP -> Asterisk (ARI) -> Call Controller -> Audio Pipeline
  -> Speech-to-Text -> Conversation Engine -> LLM -> Text-to-Speech
  -> Asterisk -> Gespraechspartner

Twilio Programmable Voice -> TwiML-Webhook -> Media-Stream-WebSocket
  -> Speech-to-Text -> Conversation Engine -> LLM -> Text-to-Speech
  -> Media-Stream-WebSocket -> Gespraechspartner
  (siehe api/twilio.py, phone/twilio_media_handler.py - Cloud-Alternative
  zu Asterisk, kein SIP-Trunk noetig, aber oeffentlicher Server/Tunnel
  erforderlich)

Conversation Engine -> Tools -> Datenbank / E-Mail / WhatsApp / Rueckruf / Do-Not-Call
```

**Provider-Pattern durchgaengig**: Jede externe Faehigkeit (STT, LLM, TTS,
Telefonie, E-Mail, WhatsApp) hat eine abstrakte Basisklasse
(`voice/stt/base.py`, `llm/base.py`, `voice/tts/base.py`, `phone/base.py`,
`tools/base.py`) und mindestens eine lokale Implementierung. Cloud-Provider
koennen spaeter ergaenzt werden, ohne die Conversation Engine anzufassen -
Twilio ist das erste Beispiel dafuer: `phone/twilio_voice.py` +
`phone/twilio_media_handler.py` nutzen dieselbe `agent/dario.py::Dario`
Fassade wie Asterisk, ohne dass an `agent/*` etwas geaendert wurde.

**Eine Conversation Engine fuer alle Kanaele**: `agent/conversation.py`
(orchestriert durch `agent/dario.py`) wird identisch von `app/chat_test.py`,
`app/local_voice_test.py` und beiden Telefonie-Pfaden
(`phone/call_controller.py` fuer Asterisk, `phone/twilio_media_handler.py`
fuer Twilio) genutzt. Keine separate vereinfachte Logik fuer Tests.

**TTS-Provider sind prozessweit gecacht** (`app/bootstrap.py::get_tts_provider`,
Signatur-basierter Dict-Cache statt `@lru_cache`, da DB-abhaengig - siehe
naechster Absatz): wichtig fuer Chatterbox, dessen ~2GB-Modell sonst bei
jedem einzelnen Anruf neu geladen wuerde. Bei Aenderungen an dieser
Cache-Logik immer pruefen, dass ein neuer Anruf nicht erneut das volle
Modell laedt.

**Prompt-Version und Stimme sind DB-gesteuert, ohne Neustart wirksam**:
`agent/dario.py::Dario.for_lead` liest bei jedem Call-Start die aktive
`database/models.py::PromptVersion` und pinnt ihren Inhalt einmalig in
`agent/context.py::ConversationContext.system_prompt` - ein bereits
laufendes Gespraech wechselt dadurch nie mitten im Gespraech die Version,
ein NEUER Call bekommt automatisch die zuletzt im Dashboard gespeicherte
Version. Analog liest `app/bootstrap.py::get_tts_provider(session)` das
aktive `database/models.py::VoiceProfile` (Referenzaufnahme + exaggeration/
cfg_weight/temperature) und cached pro Parameter-Kombination eine eigene
Chatterbox-Instanz. Ohne aktive DB-Zeile (frische Installation) gelten die
`.env`-Werte als Fallback.

**Verzeichnisstruktur** (siehe auch README.md):
```
app/        Einstiegspunkte: main.py (FastAPI), chat_test.py, local_voice_test.py, bootstrap.py
agent/      Conversation Engine, State Machine, Business Rules, Guardrails, NLU, Response-Templates
core/       Config (.env + config.yaml), Logging, Dashboard-Auth (core/auth.py)
prompts/    LLM-Systemprompt (nur fuer nicht-sicherheitskritische, offene Gespraechsteile) -
            initialer Seed fuer database/models.py::PromptVersion, danach ist die DB massgeblich
voice/      STT/TTS/VAD/Barge-In
llm/        LLM-Provider-Abstraktion + lokale llama.cpp-Anbindung
phone/      Asterisk/ARI/PJSIP, Call Controller, Twilio Programmable Voice
tools/      E-Mail, WhatsApp, Rueckruf, Do-Not-Call, zentrale Tool-Ausfuehrung
database/   SQLAlchemy Models, Repository Layer
services/   Lead/Call/Transcript/Summary Services, campaign_service.py::CampaignManager
            (Sammelanruf-Orchestrierung, siehe "Kampagnen-Engine" unten), csv_import.py
api/        FastAPI-Router: leads, calls, campaigns, auth, prompt_versions, voices,
            settings_api, do_not_call, telephony, twilio (Webhooks), live_status (WebSocket)
dashboard/  Serverseitig gerendertes Basis-Web-UI (Jinja2) - fuer den taeglichen
            Betrieb siehe stattdessen frontend/
frontend/   DVTelefonbot Dashboard: eigenstaendige Next.js/TypeScript-App (siehe
            README.md Abschnitt 17) - spricht das Backend als reine REST/WebSocket-
            API an, keine eigene Gespraechslogik
tests/      pytest-Suite
scripts/    Setup, CSV-Import
```

**Kampagnen-Engine** (`services/campaign_service.py::CampaignManager`):
orchestriert Sammelanrufe mit begrenzter Parallelitaet (Default/Max ueber
`database/models.py::AppSetting`, siehe `api/settings_api.py`) als
In-Process-`asyncio.Task` pro Kampagne. Fuehrt Gespraeche NICHT selbst -
jeder gestartete Anruf laeuft ueber den normalen, unabhaengigen Twilio-Pfad
(`TwilioProvider.start_outbound_call` -> `/twilio/voice` ->
`/twilio/media-stream`, eigene Dario-/STT-/TTS-Session pro Call). Der
Fortschritt wird bei jedem Tick aus den `Call`-Zeilen mit passender
`campaign_id` rekonstruiert (nicht aus In-Memory-Zustand) - ein
Backend-Neustart setzt eine zuvor laufende Kampagne daher automatisch auf
`PAUSED` (`CampaignManager.resume_after_restart`, in `app/main.py`
aufgerufen), statt unbeaufsichtigt neue kostenpflichtige Anrufe zu starten.

## Coding-Konventionen

- Python 3.12+, `async`/`await` durchgaengig fuer I/O-gebundenen Code.
- Type Hints ueberall, Pydantic/SQLAlchemy 2.0 fuer Datenmodelle.
- Kein monolithisches Ein-Datei-Projekt. Kein `TODO`, `pass` oder
  `NotImplementedError` als Ersatz fuer benoetigte Funktionalitaet.
- Fehlen externe Zugangsdaten (SMTP, Asterisk, WhatsApp), wird die
  Implementierung TROTZDEM vollstaendig geschrieben. Sie meldet dann beim
  Aufruf einen echten, klaren Fehler/Status (z.B. `SendResult(success=False,
  detail=...)`) statt eines Mocks oder eines TODO-Blocks.
- Kommentare nur, wenn das WARUM nicht aus dem Code hervorgeht (z.B.
  Sicherheitsentscheidung, nicht-offensichtliche Nebenwirkung).
- Deutschsprachige Docstrings/Kommentare, da das Projekt und seine
  Geschaeftslogik auf Deutsch sind.

## Sicherheitsregeln (technisch erzwungen, nicht nur im Prompt)

Diese Regeln leben in `agent/guardrails.py`, `agent/rules.py`,
`agent/state_machine.py`, `services/call_service.py` und `tools/*` - **nicht**
nur im Systemprompt (`prompts/dario_system_prompt.md`). Ein LLM kann sie nicht
umgehen.

1. **Wahrheitsschutz (Online-Auftritt/Entwurf)**: Dario darf "Wir haben uns
   Ihren Online-Auftritt angesehen" nur sagen, wenn
   `lead.online_auftritt_geprueft is True`, und "wir haben bereits einen
   Entwurf vorbereitet" nur, wenn `lead.entwurf_vorhanden is True`. Erzwungen
   durch `agent/guardrails.py::can_claim_*` / `assert_can_claim_*`, genutzt
   von jeder Methode in `agent/responses.py`, die eine dieser Behauptungen
   erzeugen koennte.
2. **Zwei-Nein-Regel**: `ConversationContext.rejection_count` (siehe
   `agent/context.py`). Beim ersten eindeutigen Nein hoechstens ein
   Entwurfsangebot (`agent/guardrails.py::can_offer_design`). Beim zweiten
   eindeutigen Nein: sofortiges, hoefliches Ende ohne weitere
   Verkaufsargumentation (`agent/guardrails.py::must_end_acquisition`,
   durchgesetzt in `agent/conversation.py`).
3. **Do-Not-Call**: Erkennung ueber `agent/nlu.py` (Intent `DO_NOT_CALL`,
   deterministische Regex-Muster, kein LLM). Persistiert in einer eigenen
   Tabelle (`database/models.py::DoNotCall`), nicht nur als Lead-Flag. **Vor
   jedem Outbound-Call** prueft `services/call_service.py::can_start_call`
   sowohl das Lead-Flag als auch die nummernbasierte Sperrliste
   (`DoNotCallRepository.is_blocked`) - die Sperre gilt auch fuer neue Leads
   mit derselben Nummer. Gilt fuer JEDEN Call-Startpfad ausnahmslos, da alle
   (Einzelanruf `api/calls.py`, Testanruf `api/telephony.py`, Kampagne
   `services/campaign_service.py`) dieselbe `CallService.can_start_call`-
   Pruefung aufrufen statt eigener Kopien - ein per Dashboard gesperrter
   Kontakt kann daher auch innerhalb einer laufenden Kampagne technisch nicht
   angerufen werden (per `tests/test_campaign_manager.py`/
   `tests/test_api_dashboard.py` verifiziert).
4. **Versand-/Terminbestaetigung**: Dario darf einen erfolgten Versand nur
   behaupten, wenn `tools/call_tools.py::ToolExecutor.send_email` /
   `send_whatsapp` tatsaechlich `success=True` zurueckgibt
   (`agent/guardrails.py::guard_send_email` / `guard_send_whatsapp`). Ein
   Rueckruftermin wird nie als fest gebucht dargestellt, solange kein
   Kalendersystem angebunden ist (`agent/guardrails.py::guard_callback`,
   `agent/responses.py::callback_without_calendar`).
5. **end_call ist real**: `phone/call_controller.py::end_call` ruft
   tatsaechlich `AsteriskProvider.end_call` (ARI Hangup); im Twilio-Pfad ruft
   `phone/twilio_media_handler.py::_hangup_real_call` tatsaechlich die
   Twilio-REST-API (`calls(sid).update(status="completed")`) - in beiden
   Faellen kein reines Setzen eines State-Feldes.
6. **Keine Fuellaute/Seufzer in TTS**: LLM-generierter Text wird vor der
   Sprachausgabe durch `agent/guardrails.py::strip_disallowed_audio_artifacts`
   bereinigt.
7. **Keine Secrets im Repository**: Alle Zugangsdaten (SMTP, Asterisk,
   WhatsApp, Twilio) ausschliesslich in `.env` (siehe `.env.example`, niemals
   mit echten Werten committen). `.gitignore` schliesst `.env`,
   Laufzeitdatenbanken, Logs und Transkripte aus. Der Twilio-Auth-Token wird
   nach dem einmaligen Eintragen in `.env` nirgends erneut ausgegeben/geloggt
   (`app/twilio_test_call.py` zeigt nur den Verifizierungsstatus, nie den
   Token selbst).
8. **Twilio-Webhooks sind signaturgeprueft**: `POST /twilio/voice` und
   `POST /twilio/status` validieren `X-Twilio-Signature` gegen
   `TWILIO_AUTH_TOKEN` (`api/twilio.py::_validate_twilio_request`,
   abschaltbar nur ueber `TWILIO_VALIDATE_SIGNATURE=false` fuer lokales
   Debugging) - ungueltige Requests werden mit 403 abgelehnt, bevor
   irgendein Call-Zustand veraendert wird.
9. **Dashboard-Auth**: alle Dashboard-API-Router (`api/leads.py`,
   `api/calls.py`, `api/campaigns.py`, `api/prompt_versions.py`,
   `api/voices.py`, `api/settings_api.py`, `api/do_not_call.py`,
   `api/telephony.py`) haengen `Depends(require_auth)` als Router-weite
   Dependency ein (`core/auth.py`) - ausgenommen bewusst nur `api/twilio.py`
   (Signaturpruefung statt Session) und `GET /api/health`/`GET
   /api/auth/me`. Twilio Auth Token, Account SID (ausser maskiert), das
   Dashboard-Passwort und alle Session-Tokens verlassen das Backend NIE im
   Klartext an das Frontend - `api/telephony.py::_mask_sid` maskiert die
   Account SID, `core/auth.py::_sessions` haelt Tokens nur serverseitig.

## Darios Rolle

Digitale, telefonische Assistenz von Digital Vision. Fuehrt primaer
ausgehende Erstgespraeche mit potenziellen Geschaeftskunden. Ziel des ersten
Gespraechs: Interesse wecken, unverbindlichen Entwurf anbieten (falls
vorhanden), Kontaktweg + Kontaktdaten aufnehmen, Uebergabe an die
Geschaeftsleitung. **Kein Vertragsabschluss im Erstgespraech.** Behauptet nie,
ein Mensch zu sein; bei direkter Frage ehrliche, kurze Antwort (siehe
`agent/responses.py::identity_disclosure`).

## Wichtige Geschaeftsregeln

- Preise: Webseiten ab 300 €/Monat (inkl. Hosting/Pflege/Support), danach nur
  laufende Betreuung ab 100 €/Monat. SEO Growth ab 200 €/Monat.
  Verwaltungssysteme individuell/auf Anfrage. Keine erfundenen
  Gesamtsummen/Laufzeiten/Rabatte (siehe `config.yaml` fuer die
  Zahlen selbst, `agent/responses.py` fuer die Formulierungen).
- Lead-Variablen (`agent/context.py::LeadData`) werden nie als leere Felder
  vorgelesen - Variablennamen werden nie ausgesprochen.
- Gespraechsstil: kurz, ruhig, professionell, maximal eine Frage pro Antwort,
  keine Callcenter-Sprache (siehe `prompts/dario_system_prompt.md`).

## Testbefehle

```bash
source .venv/bin/activate
python -m pytest tests/ -q          # vollstaendige Test-Suite
ruff check .                        # Linting
```

## Startbefehle

```bash
source .venv/bin/activate
python -m app.chat_test             # Text-Test (kein Telefon/Audio noetig)
python -m app.local_voice_test      # Voice-Test (Mikrofon/Lautsprecher, benoetigt whisper.cpp + TTS-Provider)
uvicorn app.main:app --reload       # API + einfaches Jinja2-Dashboard (http://127.0.0.1:8000)
python -m app.twilio_test_call      # echter Twilio-Testanruf (fragt vor dem Anruf nach Bestaetigung)
python -m scripts.import_leads_csv --file leads.csv

cd frontend && npm run dev          # DVTelefonbot Dashboard (http://localhost:3000, siehe README Abschnitt 17)
```

Ausfuehrliche Setup-Schritte (Python, whisper.cpp, llama.cpp, Piper/Chatterbox,
Asterisk/PJSIP, Twilio/ngrok): siehe `README.md` und `scripts/setup_mac.sh`.

## Darios Stimme (Stand: entschieden, siehe `voice/tts/chatterbox_tts.py`)

Nach mehreren Vergleichsrunden (Piper klang zu hoch/kehlig/kuenstlich) ist
`TTS_PROVIDER=chatterbox` der aktuelle Standard: Chatterbox Multilingual
(Resemble AI, MIT-Lizenz), Stimme geklont aus einer lokalen Referenzaufnahme
(`CHATTERBOX_REFERENCE_AUDIO_PATH`, lokal unter `models/voice_reference/`,
nicht im Repo), mit ruhig abgestimmten Parametern
(`exaggeration=0.22, cfg_weight=0.35, temperature=0.55`). Diese Werte nicht
ohne Grund aendern - sie sind das Ergebnis expliziter Nutzerentscheidung nach
Hoervergleichen, nicht Defaults. `voice/tts/piper_tts.py` bleibt als
schnellere, aber synthetischer klingende Alternative bestehen
(`TTS_PROVIDER=local_piper`).

## Grenzen der aktuellen Version (ehrlich dokumentiert)

- Der Telefonie-Audio-Pfad (`phone/call_controller.py`) ist aktuell
  **turn-basiert** (ARI `record` -> STT -> Dario -> TTS -> ARI `play`), nicht
  volles Streaming-Audio per RTP. Barge-In (`voice/barge_in.py`) und die
  Streaming-VAD (`voice/vad.py`) sind fertig implementiert und werden im
  lokalen Voice-Test (`app/local_voice_test.py`) per Mikrofon genutzt; die
  Anbindung an einen kontinuierlichen RTP-Audiostrom fuer verzoegerungsfreies
  Barge-In waehrend echter Telefonate ist in
  `phone/asterisk.py::start_external_media` vorbereitet, aber noch nicht an
  den Call Controller angeschlossen.
- Inbound-Telefonie (Dialplan-Vorlage in `phone/sip.py::render_extensions_conf`
  vorhanden) ist noch nicht an den Call Controller angebunden - aktueller
  Fokus liegt auf Outbound.
- Ohne konfigurierten Asterisk/whisper.cpp/llama.cpp/TTS-Provider laufen
  `app.chat_test` (Text) vollstaendig lokal ohne externe Abhaengigkeiten;
  `app.local_voice_test`, echte Anrufe und `POST /api/calls` benoetigen die
  jeweiligen lokalen Binaries/Server und melden bei deren Fehlen einen
  klaren, echten Fehler (kein stiller Fallback, keine vorgetaeuschte
  Funktion).
- **Chatterbox-Latenz noch nicht telefonietauglich**: auf diesem Mac (CPU-only,
  Apple-Silicon-MPS derzeit inkompatibel mit Chatterbox) dauert eine einzelne
  Aeusserung ca. 25-30s reine Generierungszeit nach dem Laden. Fuer
  `local_voice_test` akzeptabel, fuer ein fluessiges Telefongespraech noch zu
  langsam - vor einer echten Asterisk-/Twilio-Anbindung im Dauerbetrieb muss
  das adressiert werden (z.B. GPU-Beschleunigung, kleineres/schnelleres
  Modell oder Piper als Fallback fuer den Live-Pfad).
- **WebSocket-Ping-Timeout bei Twilio + Chatterbox**: die lange, CPU-gebundene
  Chatterbox-Generierung (siehe oben) kann den Event-Loop lange genug
  blockieren, dass Standard-WebSocket-Keepalive-Timeouts (~20s) die
  Media-Stream-Verbindung faelschlich als tot werten und mitten in Darios
  Antwort trennen. Mitigation: `uvicorn ... --ws-ping-interval 30
  --ws-ping-timeout 120` (siehe README "Twilio verbinden"). Loest nicht die
  eigentliche Latenzursache, verhindert aber den Verbindungsabbruch.
- **Twilio Media Streams liefern/erwarten G.711 mu-law bei 8kHz** - deutlich
  schmalbandiger als die uebrige Pipeline (16/22/24kHz). `voice/codecs.py`
  konvertiert verlustbehaftet in beide Richtungen; das ist normales
  Telefonie-Qualitätsniveau, kein Bug. Wichtig beim Debuggen von TTS-Audio
  im Twilio-Pfad: WAV-Dateien mit 32bit-Float-Samples (Chatterbox) muessen
  vor der int16-Wandlung explizit skaliert werden - `soundfile.read(...,
  dtype="int16")` skaliert NICHT zuverlaessig hoch und erzeugte urspruenglich
  fast lautloses/verrauschtes Audio auf der Leitung (siehe
  `phone/twilio_media_handler.py::_stream_wav_file`).
- **Anrufe mit identischer Von-/Ziel-Nummer scheitern oft mit `busy`**: bei
  einem echten Testanruf (Von=An=`+491788324883`) lieferte die Twilio-API
  Status `busy`, Dauer 0s, keine Debugger-Notifications/Alerts, und unser
  eigener `/twilio/voice`-Webhook wurde nie aufgerufen - der Anruf scheiterte
  also auf Telefonnetz-Ebene, bevor Twilio ueberhaupt versuchte, Dario zu
  verbinden. Vermutliche Ursache: (deutsche) Mobilfunknetze weisen Anrufe mit
  identischer Anrufer-/Ziel-ID haeufig als Anti-Spoofing-Massnahme zurueck.
  `app/twilio_test_call.py` warnt seither vor dem Bestaetigungs-Prompt, wenn
  `--to` mit `TWILIO_CALLER_ID` uebereinstimmt. Fuer echte Tests eine andere
  Zielnummer als die Caller-ID verwenden.
- **`<Stream>`-URL-Query-Parameter werden von Twilio nicht zuverlaessig
  durchgereicht**: ein Testanruf klingelte, wurde beim Abheben aber sofort
  wieder beendet (Twilio-Debugger-Fehler 31920 "Stream - WebSocket -
  Handshake Error"). Ursache: `call_id` stand nur als `?call_id=...` in der
  `<Stream url="...">`, Twilio schickte beim WebSocket-Verbindungsaufbau
  aber keinen Query-String mit - unser Server lehnte die Verbindung mangels
  Pflichtparameter mit 403 ab, bevor Dario ueberhaupt antworten konnte.
  Behoben durch ein `<Parameter name="call_id" .../>`-Element (offizieller
  Twilio-Mechanismus, kommt zuverlaessig im "start"-Event als
  `customParameters` an) - siehe `phone/twilio_voice.py::build_connect_stream_twiml`
  und `api/twilio.py::_await_start_event`. Die URL behaelt den Query-Parameter
  zusaetzlich als harmlosen Fallback.
- **Barge-In war faktisch tot**: die urspruengliche `TwilioMediaStreamSession`
  las eingehende WebSocket-Nachrichten NUR waehrend der Zuhoer-Phase - waehrend
  Darios eigener TTS-Ausgabe (`_speak()`) wurde nie `receive_text()` aufgerufen,
  wodurch Anrufer-Sprache waehrend der Wiedergabe schlicht nie verarbeitet
  wurde. Zusaetzlich wurden gesendete Audio-Chunks ohne Echtzeit-Kadenz
  moeglichst schnell rausgehauen, was das Zeitfenster fuer eine Unterbrechung
  auf praktisch Null reduzierte. Behoben durch einen einzigen, durchgehend
  laufenden Empfangs-Task fuer die gesamte Session-Dauer (liest immer,
  unabhaengig vom Sprech-/Zuhoer-Status) und Echtzeit-Pacing beim Senden
  (20ms/Frame) - siehe `phone/twilio_media_handler.py::_receive_loop`. Mit
  simuliertem Twilio-Stream verifiziert: Unterbrechung mitten im Satz loest
  jetzt zuverlaessig ein `clear`-Event aus.
- **WebSocket wurde nach regulaerem Gespraechsende nicht sauber geschlossen**:
  fuehrte bei manchen Clients zu einem abrupten Verbindungsabbruch statt eines
  Close-Handshakes (kosmetisch - der eigentliche Anruf-Status wurde bereits
  korrekt in der DB persistiert). Behoben durch explizites `websocket.close()`
  nach normalem Session-Ende (`api/twilio.py::twilio_media_stream`).
- **`WHISPER_MODEL_PATH` Standard auf `ggml-medium.bin` umgestellt** (vorher
  `small`): bei einem vollstaendigen simulierten Testanruf ueber die 8kHz-
  Telefonqualitaet erkannte `small` eine diktierte E-Mail-Adresse
  ("info at ... punkt de") ohne jedes "@"-Zeichen - die Kontaktdatenerfassung
  scheiterte komplett. Mit `medium` wurde derselbe Anruf korrekt bis zur
  E-Mail-Bestaetigung und Uebergabe durchlaufen, inklusive korrektem Speichern
  in der Datenbank. `small` bleibt als schnellere Alternative verfuegbar,
  ist fuer telefonisch diktierte Kontaktdaten aber nicht zu empfehlen. Ein
  bestimmtes Wort ("Tschüss", in dieser Piper-Synthese) wurde auch mit
  `medium` als "Schatz"/"Schutz" gehoert - "Auf Wiederhören" wurde dagegen in
  allen Tests korrekt erkannt.
- **DVTelefonbot Dashboard (`frontend/`, siehe README Abschnitt 17) - Stand
  dieser Version:**
  - `api/settings_api.py`: nur die Kampagnen-Parallelitaets-Einstellungen
    (Standard/Max/Pause zwischen Anrufen) sind echt an
    `services/campaign_service.py` angebunden. Agent-Name/Firma/Standort und
    die Anruf-Timeouts (Cooldown/Warte-/Stille-Timeout) werden im
    Einstellungen-Bereich nur informativ aus `.env` angezeigt, nicht per
    Dashboard ueberschreibbar - `_EDITABLE_KEYS` in `api/settings_api.py`
    bewusst schmal gehalten, statt dekorative, wirkungslose Eingabefelder
    anzubieten.
  - Live-Status (`api/live_status.py`, `/ws/live-status`) ist Polling-basiert
    (Backend fragt alle 1.5s die DB ab und sendet das Ergebnis), kein echtes
    Event-Pub/Sub aus der Twilio-Media-Stream-Session heraus - fuer eine
    Status-Anzeige ausreichend, aber kein Ersatz fuer echtes Streaming, falls
    das je gebraucht wird.
  - Kein automatisierter Browser-/E2E-Test des Frontends (kein Headless-
    Browser in dieser Entwicklungsumgebung verfuegbar). Verifiziert wurden:
    `npm run build` und `npm run lint` (beide fehlerfrei), die Backend-API
    per `pytest` (`tests/test_api_dashboard.py`, `tests/test_campaign_manager.py`,
    `tests/test_auth.py`, echte FastAPI-App, Fake-Twilio-Provider statt
    echter Anrufe), sowie ein manueller Rauchtest per `curl` gegen das
    tatsaechlich laufende Backend (Login/Cookie/geschuetzte Routen,
    automatisches Seeding von Prompt-Version und Stimme aus der bestehenden
    Produktionskonfiguration). Ein Klick-Durchlauf im echten Browser vor
    produktivem Einsatz wird empfohlen.
  - Beim Login-Cookie mit `expires=<datetime>` an `Response.set_cookie`
    uebergeben, NICHT `expires=<int>`: Pythons `http.cookies` interpretiert
    einen rohen `int` bei `expires` als Sekunden-Offset ab JETZT, nicht als
    Unix-Timestamp - ein versehentlich als Timestamp uebergebener `int` fuehrt
    zu einem Ablaufdatum ~56 Jahre in der Zukunft (in dieser Version
    gefunden und behoben, siehe `api/auth.py::login`).
