#!/usr/bin/env bash
# Digital Vision Dario - Setup-Hilfe fuer macOS.
#
# Prueft/installiert die benoetigten Werkzeuge. Nimmt KEINE gefaehrlichen
# oder unnoetigen Systemaenderungen vor - fragt vor jeder Installation nach
# Bestaetigung und bricht bei Fehlern sauber ab (set -e).
#
# Aufruf:
#   bash scripts/setup_mac.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

info()  { echo -e "${GREEN}==>${RESET} $1"; }
warn()  { echo -e "${YELLOW}!!${RESET} $1"; }

confirm() {
    read -r -p "$1 [j/N] " reply
    [[ "$reply" =~ ^([jJ]|[yY])$ ]]
}

info "Digital Vision Dario - Setup fuer macOS"

# --- Homebrew -----------------------------------------------------------
if ! command -v brew >/dev/null 2>&1; then
    warn "Homebrew ist nicht installiert. Bitte manuell installieren: https://brew.sh"
    exit 1
fi
info "Homebrew gefunden: $(brew --version | head -1)"

# --- Python 3.12 ----------------------------------------------------------
if command -v python3.12 >/dev/null 2>&1; then
    info "Python 3.12 gefunden: $(python3.12 --version)"
else
    if confirm "Python 3.12 nicht gefunden. Jetzt via Homebrew installieren?"; then
        brew install python@3.12
    else
        warn "Python 3.12 wird fuer dieses Projekt benoetigt (pyproject.toml)."
    fi
fi

# --- Virtualenv + Abhaengigkeiten ------------------------------------------
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    if confirm "Kein .venv gefunden. Jetzt anlegen?"; then
        python3.12 -m venv "$PROJECT_ROOT/.venv"
    fi
fi

if [ -d "$PROJECT_ROOT/.venv" ]; then
    info "Aktiviere .venv und installiere Python-Abhaengigkeiten"
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.venv/bin/activate"
    pip install --upgrade pip >/dev/null
    pip install -e ".[dev,voice]"
    info "Python-Abhaengigkeiten installiert."
fi

# --- ffmpeg -----------------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
    info "ffmpeg gefunden."
else
    if confirm "ffmpeg nicht gefunden. Jetzt via Homebrew installieren?"; then
        brew install ffmpeg
    fi
fi

# --- whisper.cpp --------------------------------------------------------
if command -v whisper-cli >/dev/null 2>&1; then
    info "whisper.cpp (whisper-cli) gefunden."
else
    warn "whisper.cpp nicht gefunden."
    if confirm "Jetzt via Homebrew installieren (brew install whisper-cpp)?"; then
        brew install whisper-cpp
    else
        cat <<'EOF'
   Manuelle Installation:
     git clone https://github.com/ggerganov/whisper.cpp
     cd whisper.cpp && make
   Anschliessend WHISPER_CPP_BINARY in .env auf den Pfad zum Binary setzen.
EOF
    fi
fi

mkdir -p "$PROJECT_ROOT/models/whisper"
if [ ! -f "$PROJECT_ROOT/models/whisper/ggml-medium.bin" ]; then
    warn "Kein Whisper-Modell in models/whisper/ gefunden."
    if confirm "Deutsches Whisper-Modell (medium, ~1.5GB) jetzt herunterladen?"; then
        curl -L -o "$PROJECT_ROOT/models/whisper/ggml-medium.bin" \
            "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.bin"
    fi
fi

# --- llama.cpp ------------------------------------------------------------
if command -v llama-server >/dev/null 2>&1; then
    info "llama.cpp (llama-server) gefunden."
else
    warn "llama.cpp nicht gefunden."
    if confirm "Jetzt via Homebrew installieren (brew install llama.cpp)?"; then
        brew install llama.cpp
    else
        cat <<'EOF'
   Manuelle Installation:
     git clone https://github.com/ggerganov/llama.cpp
     cd llama.cpp && cmake -B build && cmake --build build --config Release
   Anschliessend ein GGUF-Modell (z.B. ein instruction-tuned 7-8B Modell mit
   guten Deutschkenntnissen) herunterladen und starten mit:
     llama-server -m ./models/llm/model.gguf --port 8080
EOF
    fi
fi

# --- Piper (TTS) ------------------------------------------------------------
if command -v piper >/dev/null 2>&1; then
    info "Piper gefunden."
else
    warn "Piper (lokale TTS) nicht gefunden."
    if confirm "Jetzt via pip installieren (pip install piper-tts)?"; then
        pip install piper-tts
    else
        cat <<'EOF'
   Manuelle Installation: https://github.com/rhasspy/piper
   Empfohlene deutsche maennliche Stimme: de_DE-thorsten-medium
EOF
    fi
fi

mkdir -p "$PROJECT_ROOT/models/piper"
if [ ! -f "$PROJECT_ROOT/models/piper/de_DE-thorsten-medium.onnx" ]; then
    warn "Kein Piper-Sprachmodell in models/piper/ gefunden."
    if confirm "de_DE-thorsten-medium jetzt herunterladen?"; then
        BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium"
        curl -L -o "$PROJECT_ROOT/models/piper/de_DE-thorsten-medium.onnx" "$BASE_URL/de_DE-thorsten-medium.onnx"
        curl -L -o "$PROJECT_ROOT/models/piper/de_DE-thorsten-medium.onnx.json" "$BASE_URL/de_DE-thorsten-medium.onnx.json"
    fi
fi

# --- Asterisk (optional, fuer echte Telefonie) -----------------------------
if command -v asterisk >/dev/null 2>&1; then
    info "Asterisk gefunden."
else
    warn "Asterisk nicht gefunden (nur fuer echte Telefonanrufe noetig, nicht fuer Text-/Voice-Test)."
    if confirm "Jetzt via Homebrew installieren (brew install asterisk)?"; then
        brew install asterisk
    else
        echo "   Siehe README.md Abschnitt 'Asterisk installieren' fuer Details."
    fi
fi

# --- .env -------------------------------------------------------------------
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    info ".env aus .env.example erstellt - bitte mit echten Werten befuellen."
fi

info "Setup abgeschlossen. Naechste Schritte:"
echo "  1. source .venv/bin/activate"
echo "  2. python -m app.chat_test          # Text-Test ohne Telefon/Audio"
echo "  3. python -m app.local_voice_test   # Voice-Test mit Mikrofon/Lautsprecher"
echo "  4. uvicorn app.main:app --reload    # API + Dashboard starten"
