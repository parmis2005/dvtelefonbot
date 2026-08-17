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
  - `api/settings_api.py`: alle dort editierbaren Werte (Agent-Name/Firma/
    Standort, Anruf-Cooldown/Wartezeit/Stille-Timeout, Kampagnen-Standard-/
    Max-Parallelitaet/Pause zwischen Anrufen) sind echt verdrahtet, siehe
    `services/effective_settings.py::get_effective_settings` - liest
    `database/models.py::AppSetting`-Ueberschreibungen und ueberlagert sie
    zur Call-Start-Zeit auf die .env-Basiswerte (`core/config.py::Settings`),
    OHNE den prozessweit gecachten Settings-Singleton zu mutieren
    (`Settings.model_copy(update=...)` statt In-Place-Zuweisung - sonst
    wuerden gleichzeitige Anrufe sich gegenseitig Werte ueberschreiben).
    Eingebunden in `app/bootstrap.py::build_app_context(session)` (Agent-
    Name/Firma/Standort -> `ConversationEngine`/`ResponseBank`, Wartezeit ->
    `phone/twilio_media_handler.py`, Stille-Timeout -> `EndpointDetector`)
    und `services/call_service.py::CallService._effective_call_cooldown`
    (liest direkt ueber `self.session`, gilt daher automatisch fuer JEDEN
    Call-Startpfad: Einzelanruf, Dashboard-Testanruf, Kampagne - mit einer
    bewussten Ausnahme, siehe naechster Punkt). Wie bei Prompt-Version und
    Stimme gilt: ein bereits laufendes Gespraech behaelt seine beim Start
    gepinnten Werte, ein NEUER Call bekommt automatisch die zuletzt im
    Dashboard gespeicherten Werte - kein Backend-Neustart noetig.
  - **Cooldown-Ausnahme fuer `app/twilio_test_call.py`**: manuell mit "ja"
    bestaetigte CLI-Testanrufe umgehen den Cooldown bewusst
    (`CallService.can_start_call`/`start_call(..., ignore_cooldown=True)`),
    damit ein Testanruf nicht am Cooldown desselben Test-Leads aus einem
    vorherigen Testlauf scheitert. Gilt ausschliesslich fuer diesen einen
    Aufrufer - Einzelanruf (`api/calls.py`), Dashboard-Testanruf
    (`api/telephony.py`) und Kampagnen (`services/campaign_service.py`)
    lassen das Argument bewusst weg und bleiben vom Cooldown unveraendert
    betroffen. Do-Not-Call und Telefonnummer-Validierung bleiben von
    `ignore_cooldown` in jedem Fall unberuehrt (siehe
    `tests/test_call_status.py::test_ignore_cooldown_still_respects_do_not_call`).
  - **"Sind Sie noch da?" bei Wartezeit-Ablauf neu gebaut**
    (`agent/dario.py::Dario.check_wait_timeout`, aufgerufen aus
    `phone/twilio_media_handler.py`'s Hauptschleife nach jeder ergebnislosen
    Zuhoer-Phase): existierte vorher nur als unverdrahtetes Geruest
    (`ConversationContext.wait_started_at`/`still_there_asked`,
    `ResponseBank.still_there()` waren definiert, aber nirgends
    zusammengeschaltet - `settings.wait_timeout` wurde ausschliesslich vom
    Asterisk-Pfad gelesen, nie vom verifizierten Twilio-Pfad). Greift nur,
    wenn der Kunde zuvor explizit um eine Wartepause gebeten hat
    (`context.wait_mode`): nach Ablauf der Wartezeit fragt Dario einmalig
    "Sind Sie noch da?", bleibt fuer eine zweite gleich lange Gnadenfrist
    still und beendet das Gespraech erst danach hoeflich - ueber denselben
    `_finalize_call()`-Pfad wie jedes reguläre Gespraechsende (Transkript/
    Zusammenfassung werden dabei genauso persistiert). Mit
    `tests/test_effective_settings.py` verifiziert (inkl. Persistenz-Check).
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
- **Echter Testanruf brach nach dem Abheben mit Fehleransage ab (Twilio-Fehler
  11200)**: Root-Cause-Analyse ueber die Twilio-REST-API (`client.calls(sid).
  notifications.list()`) ergab `ErrorCode 11200, Msg="Got HTTP 502 response to
  https://.../twilio/voice?call_id=1"` - **kein Code-Fehler**, sondern der
  ngrok-Tunnel lief zwar (seit Stunden aktiv), aber zum exakten Anrufzeitpunkt
  war kein Backend-Prozess auf Port 8000 erreichbar (502 kam vom ngrok-Edge,
  nicht von FastAPI). Lokale `logs/dario.log`-Eintraege zum Anrufzeitpunkt
  fehlten komplett (nur Test-Suite-Rauschen sichtbar) - das allein war schon
  der erste Hinweis, dass der Server zu dem Zeitpunkt gar nicht lief.
  Trotzdem als Haertung umgesetzt, um genau diese Fehlerklasse kuenftig VOR
  einem echten, kostenpflichtigen Anruf sichtbar zu machen statt erst danach
  im Twilio-Debugger:
  - `services/telephony_diagnostics.py::check_webhook_reachable` (per
    `httpx`-GET gegen `{TWILIO_PUBLIC_BASE_URL}/api/health`, 5s Timeout) -
    neu genutzt von `api/telephony.py::telephony_status` (Dashboard zeigt
    jetzt `public_base_url_reachable`, nicht nur "URL gesetzt"), sowie als
    harter Block VOR dem Ausloesen eines echten Anrufs in
    `api/telephony.py::trigger_test_call`, `api/calls.py::create_twilio_call`
    und `services/campaign_service.py::CampaignManager._run_campaign` (dort
    bewusst NICHT als permanenter Skip wie bei Do-Not-Call behandelt, sondern
    als transiente Bedingung, die im naechsten Poll-Tick erneut geprueft
    wird - siehe `CampaignManager._webhook_reachable`). `app/twilio_test_call.py`
    nutzt denselben Helper (vorher lokal dupliziert).
  - Zur Verifikation ohne echten Anruf: `tests/test_twilio_media_stream_e2e.py`
    - ein neuer, permanenter simulierter End-to-End-Test des ECHTEN
    `/twilio/voice` -> `/twilio/media-stream`-Pfads (nicht nur der isolierten
    Conversation Engine), der genau diesen Codepfad unabhaengig von
    Infrastruktur-Verfuegbarkeit durchspielt: connected/start/media/stop-
    Events, `build_app_context(session)`, `Dario.for_lead`, ein echter STT->
    Engine->TTS-Umlauf, natuerliche Verabschiedung, echtes `end_call` ueber
    `TwilioProvider`, sauberes WebSocket-Close, Transkript-/Zusammenfassungs-
    Persistenz, sowie ein dedizierter Resilienz-Test (TTS-Absturz mitten im
    Call darf weder den Server noch andere Calls beeintraechtigen). Mockt nur
    STT/TTS/TwilioProvider an der Provider-Grenze (Chatterbox/whisper.cpp
    sind fuer die schnelle Test-Suite ungeeignet), alles andere laeuft echt.
  - Bei dieser Gelegenheit auch `agent/responses.py::ResponseBank.greeting`
    korrigiert: wich vom mittlerweile verbindlich vorgegebenen Wortlaut ("Guten
    Tag! Hier ist Dario, der digitale Assistent von Digital Vision aus
    Moenchengladbach. Haben Sie gerade einen Moment Zeit?") ab - die alte
    Version fragte stattdessen sofort nach der richtigen Ansprechperson fuer
    das jeweilige Unternehmen (das uebernimmt jetzt ausschliesslich die
    separate Gatekeeper-Logik). Mit `tests/test_conversation_flow.py::
    test_opening_line_matches_mandated_greeting` als Wortlaut-Regressionstest
    abgesichert. Alle uebrigen woertlich vorgegebenen Formulierungen
    (Gatekeeper, Nachricht ausrichten, Zwei-Nein-Regel, Wait-Mode, Preise,
    Verabschiedung, Do-Not-Call) wurden Zeile fuer Zeile mit `agent/
    responses.py` abgeglichen und stimmten bereits ueberein.
- **Dashboard-Login "tat nichts" (`localhost` vs. `127.0.0.1`)**: das Backend
  war erreichbar, der Login-Request lief erfolgreich (200, korrektes
  Set-Cookie ueber curl verifiziert), aber der Browser landete nie im
  Dashboard. Ursache: `frontend/.env.local` zeigte auf
  `http://127.0.0.1:8000`, waehrend das Dashboard selbst unter
  `http://localhost:3000` lief - Browser werten `localhost` und `127.0.0.1`
  als unterschiedliche SITES (nicht nur unterschiedliche Origins), wodurch
  das `SameSite=Lax`-Session-Cookie (`core/auth.py`) bei jedem Cross-Site-
  Fetch NACH dem Login verworfen wird (das Set-Cookie selbst kommt noch an,
  wird aber nie zurueckgeschickt). Behoben durch `NEXT_PUBLIC_API_BASE_URL=
  http://localhost:8000` (passend zum Dashboard-Host) in `.env.local`/
  `.env.example` sowie denselben Fallback-Default in `src/lib/api.ts` und
  `src/lib/useLiveStatus.ts`. Zwei Fallstricke beim Beheben selbst: (1)
  `NEXT_PUBLIC_*`-Variablen werden nur beim Start des Dev-Servers eingebaut,
  nicht live nachgeladen - ein Neustart ist Pflicht; (2) Turbopacks Dev-Cache
  hatte den alten Wert bereits kompiliert und lieferte ihn nach einem reinen
  Prozess-Neustart weiter aus - erst `rm -rf frontend/.next` plus Neustart
  baute den neuen Wert tatsaechlich ein (verifiziert durch Grep im
  kompilierten Chunk: `("TURBOPACK compile-time value", "http://localhost:
  8000")`). Kompletter Login/Logout-Zyklus danach per curl mit Origin-Header
  gegen das echte laufende Backend verifiziert.
- **Chatterbox war bei ueberlappenden Anrufen nicht nebenlaeufigkeitssicher
  (Root-Cause-Kandidat fuer "Rauschen statt Sprache")**: `ChatterboxTTSProvider`
  ist prozessweit gecacht und wird von ALLEN gleichzeitigen Anrufen geteilt
  (`app/bootstrap.py::get_tts_provider`). Chatterbox' `generate()` ruft bei
  jedem Aufruf intern `prepare_conditionals()` auf, was das GETEILTE
  Modell-Attribut `self.conds` ueberschreibt statt einen per-Aufruf-Zustand zu
  verwenden - lief `synthesize()` fuer zwei Anrufe zeitlich ueberlappend
  (z.B. zwei Kampagnen-Calls, deren TTS-Antworten kurz gegeneinander
  versetzt eintrafen), konnte der zweite Aufruf die Konditionierung des
  ersten MITTEN in dessen Generierung ueberschreiben - beobachtbares Symptom
  auf der Leitung: verzerrtes/rauschendes statt verstaendliches Audio. Ein rein
  lokaler Einzelanruf-Test zeigt das nicht (kein zweiter ueberlappender
  Aufruf), weshalb der Fehler bei einem isolierten Testanruf nicht zwingend
  auftritt, aber im echten Mehr-Anrufe-Betrieb (Abschnitt "10 parallele
  Gespraeche") reproduzierbar waere. Behoben durch einen
  `asyncio.Lock` (`ChatterboxTTSProvider._generate_lock`), der alle
  `generate()`-Aufrufe auf demselben Modell serialisiert - CPU-gebunden ohnehin
  nicht sinnvoll parallelisierbar. Mit `tests/test_chatterbox_concurrency.py`
  verifiziert (ein Fake-Modell erkennt und meldet einen gleichzeitigen
  Eintritt in `generate()`; der Test wurde durch testweises Entfernen des
  Locks als tatsaechlich wirksam bestaetigt, statt sich nur auf die
  Code-Lektuere zu verlassen).
  **Wichtige Konsequenz fuer 10 parallele Gespraeche**: der Lock macht
  gleichzeitige TTS-Anfragen KORREKT statt gleichzeitig SCHNELL - bei mehreren
  Anrufen, deren Antworten zeitlich zusammenfallen, wird Chatterbox pro
  Aeusserung (~25-40s auf dieser CPU-only-Hardware, siehe naechster Punkt)
  strikt nacheinander abgearbeitet, nicht parallel. Bei einem echten Burst von
  bis zu 10 gleichzeitigen Anrufen kann sich das auf mehrere Minuten
  Wartezeit fuer spaete Anrufe aufsummieren. Das ist der korrekte Trade-off
  (verstaendliches, aber wartendes Audio statt schnelles, aber korruptes
  Audio), loest aber nicht das grundsaetzliche, bereits weiter oben
  dokumentierte Latenzproblem von Chatterbox auf CPU - fuer echten
  telefonietauglichen Mehr-Anrufe-Betrieb bleibt GPU-Beschleunigung,
  ein kleineres/schnelleres Modell oder mehrere unabhaengige Modell-Instanzen
  (z.B. ein Prozess/Modell pro gleichzeitigem Anruf statt ein geteiltes
  Singleton) ein offener Punkt.
- **Lokaler Audio-Kontrolltest bestaetigt: der Audio-AUSGABEPFAD selbst
  (Chatterbox -> float32-WAV -> Resampling auf 8kHz -> mu-law -> Twilio-
  Frames) ist korrekt** (siehe `audio_diagnostics/run_control_test.py`,
  erzeugt und archiviert ein reales TTS-Ergebnis mit der aktiven
  Dario-Stimme, die exakt fuer Twilio konvertierte mu-law-Version und eine
  hoerbare Rueckkonvertierung): bei einem echten Lauf mit der Begruessung
  lag der mu-law-Roundtrip-SNR bei 37.4 dB (typisch fuer G.711: 35-38 dB,
  also kein Qualitaetsverlust ueber das fuer Telefonie inhaerente Mass
  hinaus) und nur 4 von 188.160 Samples lagen minimal (Peak 1.06) ueber
  Vollausschlag. Die eigene mu-law-Kodierung (`voice/codecs.py`) wurde
  zusaetzlich gegen Pythons Referenzimplementierung `audioop.lin2ulaw`/
  `ulaw2lin` verifiziert (< 1% Abweichung, jeweils hoechstens eine
  Quantisierungsstufe, reine Rundungsdifferenzen an Segmentgrenzen - siehe
  `tests/test_twilio_audio_format.py`). Der Codec/Resampling-Pfad ist damit
  als Root Cause fuer gemeldetes "Rauschen statt Sprache" ausgeschlossen;
  der oben dokumentierte Nebenlaeufigkeits-Bug ist der einzige im Code
  gefundene, tatsaechlich reproduzierbare Kandidat dafuer.
- **Barge-In auf dem echten Twilio-Media-Stream-Pfad war bisher ungetestet**:
  `tests/test_barge_in.py` deckt nur `voice/barge_in.py::BargeInController`
  ab (nur fuer `app/local_voice_test.py`, den Mikrofon-Pfad, relevant) - der
  fuer Twilio tatsaechlich verwendete, komplett separate Mechanismus
  (`phone/twilio_media_handler.py::TwilioMediaStreamSession._receive_loop` /
  `_process_vad_frames` / `_send_clear`, siehe "Barge-In war faktisch tot"
  weiter oben) hatte keinen End-to-End-Test ueber den echten
  `/twilio/voice` -> `/twilio/media-stream`-Pfad. Neu:
  `tests/test_twilio_barge_in_e2e.py` verifiziert ueber den echten Pfad,
  dass eine waehrend Darios Sprachausgabe eintreffende "media"-Nachricht (a)
  vom durchgehend laufenden Empfangs-Task erkannt wird, (b) ein "clear"-
  Event an Twilio ausloest, (c) die Wiedergabe nachweislich VORZEITIG
  abbricht (deutlich weniger Frames als bei vollstaendiger Wiedergabe), und
  (d) das Gespraech danach normal weiterlaeuft (STT/Antwort/end_call
  funktionieren weiter). Ergaenzend stellt eine neue Assertion im
  bestehenden `test_full_call_greeting_turn_and_natural_farewell` sicher,
  dass reine Stille (echte WebRTC-VAD, nicht gemockt) KEIN falsches
  Barge-In (kein "clear"-Event) ausloest.
