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

Conversation Engine -> Tools -> Datenbank / E-Mail / WhatsApp / Rueckruf / Do-Not-Call
```

**Provider-Pattern durchgaengig**: Jede externe Faehigkeit (STT, LLM, TTS,
Telefonie, E-Mail, WhatsApp) hat eine abstrakte Basisklasse
(`voice/stt/base.py`, `llm/base.py`, `voice/tts/base.py`, `phone/base.py`,
`tools/base.py`) und mindestens eine lokale Implementierung. Cloud-Provider
koennen spaeter ergaenzt werden, ohne die Conversation Engine anzufassen.

**Eine Conversation Engine fuer alle Kanaele**: `agent/conversation.py`
(orchestriert durch `agent/dario.py`) wird identisch von `app/chat_test.py`,
`app/local_voice_test.py` und dem Telefonie-Pfad (`phone/call_controller.py`)
genutzt. Keine separate vereinfachte Logik fuer Tests.

**Verzeichnisstruktur** (siehe auch README.md):
```
app/        Einstiegspunkte: main.py (FastAPI), chat_test.py, local_voice_test.py, bootstrap.py
agent/      Conversation Engine, State Machine, Business Rules, Guardrails, NLU, Response-Templates
core/       Config (.env + config.yaml) und Logging
prompts/    LLM-Systemprompt (nur fuer nicht-sicherheitskritische, offene Gespraechsteile)
voice/      STT/TTS/VAD/Barge-In
llm/        LLM-Provider-Abstraktion + lokale llama.cpp-Anbindung
phone/      Asterisk/ARI/PJSIP, Call Controller
tools/      E-Mail, WhatsApp, Rueckruf, Do-Not-Call, zentrale Tool-Ausfuehrung
database/   SQLAlchemy Models, Repository Layer
services/   Lead/Call/Transcript/Summary Services (Validierung oberhalb des Repository Layers)
api/        FastAPI-Router (Leads, Calls)
dashboard/  Serverseitig gerendertes Web-UI (Jinja2)
tests/      pytest-Suite
scripts/    Setup, CSV-Import
```

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
   mit derselben Nummer.
4. **Versand-/Terminbestaetigung**: Dario darf einen erfolgten Versand nur
   behaupten, wenn `tools/call_tools.py::ToolExecutor.send_email` /
   `send_whatsapp` tatsaechlich `success=True` zurueckgibt
   (`agent/guardrails.py::guard_send_email` / `guard_send_whatsapp`). Ein
   Rueckruftermin wird nie als fest gebucht dargestellt, solange kein
   Kalendersystem angebunden ist (`agent/guardrails.py::guard_callback`,
   `agent/responses.py::callback_without_calendar`).
5. **end_call ist real**: `phone/call_controller.py::end_call` ruft
   tatsaechlich `AsteriskProvider.end_call` (ARI Hangup) - kein reines
   Setzen eines State-Feldes.
6. **Keine Fuellaute/Seufzer in TTS**: LLM-generierter Text wird vor der
   Sprachausgabe durch `agent/guardrails.py::strip_disallowed_audio_artifacts`
   bereinigt.
7. **Keine Secrets im Repository**: Alle Zugangsdaten (SMTP, Asterisk,
   WhatsApp) ausschliesslich in `.env` (siehe `.env.example`, niemals mit
   echten Werten committen). `.gitignore` schliesst `.env`,
   Laufzeitdatenbanken, Logs und Transkripte aus.

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
python -m app.local_voice_test      # Voice-Test (Mikrofon/Lautsprecher, benoetigt whisper.cpp + Piper)
uvicorn app.main:app --reload       # API + Dashboard (http://127.0.0.1:8000)
python -m scripts.import_leads_csv --file leads.csv
```

Ausfuehrliche Setup-Schritte (Python, whisper.cpp, llama.cpp, Piper,
Asterisk/PJSIP): siehe `README.md` und `scripts/setup_mac.sh`.

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
- Ohne konfigurierten Asterisk/whisper.cpp/llama.cpp/Piper laufen
  `app.chat_test` (Text) vollstaendig lokal ohne externe Abhaengigkeiten;
  `app.local_voice_test`, echte Anrufe und `POST /api/calls` benoetigen die
  jeweiligen lokalen Binaries/Server und melden bei deren Fehlen einen
  klaren, echten Fehler (kein stiller Fallback, keine vorgetaeuschte
  Funktion).
