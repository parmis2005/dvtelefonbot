#!/usr/bin/env node
/**
 * Lokaler Dashboard-Startbefehl fuer Digital Vision Dario: `npm run dashboard`
 * im Projekt-Wurzelverzeichnis startet Backend (FastAPI/uvicorn ueber die
 * vorhandene .venv, Port 8000) UND Frontend (Next.js-Dashboard, Port 3000)
 * gemeinsam, prueft vorher, ob die Ports schon belegt sind (keine
 * doppelten Prozesse), wartet auf einen erfolgreichen Backend-Health-Check
 * und haelt beide Prozesse am Leben, bis sie ueber Ctrl+C sauber beendet
 * werden. Ersetzt das manuelle `source .venv/bin/activate && uvicorn ...`
 * plus `cd frontend && npm run dev` in zwei Terminals.
 *
 * Bewusst als Node-Skript statt als Bash-Skript: Node ist ueber das
 * Frontend ohnehin eine harte Voraussetzung, und `child_process` erlaubt
 * eine saubere, plattformnahe Prozessverwaltung (Health-Check-Polling,
 * gezieltes Beenden NUR der selbst gestarteten Prozesse) ohne zusaetzliche
 * Abhaengigkeiten.
 */

"use strict";

const path = require("path");
const fs = require("fs");
const net = require("net");
const http = require("http");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const FRONTEND_DIR = path.join(ROOT, "frontend");
const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3000;
const HEALTH_URL = `http://localhost:${BACKEND_PORT}/api/health`;
const DASHBOARD_URL = `http://localhost:${FRONTEND_PORT}`;

const COLOR = {
  reset: "\x1b[0m",
  dim: "\x1b[2m",
  cyan: "\x1b[36m",
  magenta: "\x1b[35m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
};

function log(prefix, color, message) {
  process.stdout.write(`${color}[${prefix}]${COLOR.reset} ${message}\n`);
}

const logDev = (msg) => log("dev", COLOR.cyan, msg);
const logDevOk = (msg) => log("dev", COLOR.green, msg);
const logDevWarn = (msg) => log("dev", COLOR.yellow, msg);
const logDevErr = (msg) => log("dev", COLOR.red, msg);

/** Prueft nicht-invasiv, ob bereits etwas auf dem Port lauscht (Verbindungsversuch statt eigenem Bind). */
function isPortInUse(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ port, host: "127.0.0.1" });
    const onFailure = () => {
      socket.destroy();
      resolve(false);
    };
    socket.setTimeout(800, onFailure);
    socket.once("error", onFailure);
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
  });
}

function httpGetOk(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 2000 }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => resolve({ ok: res.statusCode === 200, body }));
    });
    req.on("timeout", () => req.destroy());
    req.on("error", () => resolve({ ok: false, body: "" }));
  });
}

async function waitForHttpOk(url, { timeoutMs, intervalMs, label }) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const result = await httpGetOk(url);
    if (result.ok) return result;
    if (Date.now() > deadline) return { ok: false, body: "" };
    logDev(`Warte auf ${label} ...`);
    await new Promise((r) => setTimeout(r, intervalMs));
  }
}

/** Leitet stdout/stderr eines Kindprozesses zeilenweise mit Praefix weiter. */
function pipeWithPrefix(stream, prefix, color) {
  let buffer = "";
  stream.on("data", (chunk) => {
    buffer += chunk.toString();
    let idx;
    while ((idx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 1);
      if (line.trim()) log(prefix, color, line);
    }
  });
  stream.on("end", () => {
    if (buffer.trim()) log(prefix, color, buffer);
  });
}

const spawnedChildren = []; // nur selbst gestartete Prozesse - siehe shutdown()
let shuttingDown = false;
let exitCode = 0;

function killChild(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.killed) return resolve();
    const forceKillTimer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        /* Prozess bereits weg */
      }
    }, 5000);
    child.once("exit", () => {
      clearTimeout(forceKillTimer);
      resolve();
    });
    try {
      child.kill("SIGTERM");
    } catch {
      clearTimeout(forceKillTimer);
      resolve();
    }
  });
}

async function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  exitCode = code;
  if (spawnedChildren.length > 0) {
    logDev("Beende die von diesem Befehl gestarteten Prozesse ...");
    await Promise.all(spawnedChildren.map(({ child }) => killChild(child)));
    logDevOk("Alle gestarteten Prozesse sauber beendet.");
  }
  process.exit(exitCode);
}

process.on("SIGINT", () => {
  logDev("Ctrl+C erkannt.");
  shutdown(0);
});
process.on("SIGTERM", () => shutdown(0));

function watchForUnexpectedExit(child, name) {
  child.on("exit", (code, signal) => {
    if (shuttingDown) return; // erwarteter Teil des eigenen Shutdowns
    logDevErr(
      `${name} wurde unerwartet beendet (code=${code}, signal=${signal}) - stoppe den jeweils anderen Prozess.`
    );
    shutdown(1);
  });
}

async function startBackend() {
  const inUse = await isPortInUse(BACKEND_PORT);
  if (inUse) {
    logDevWarn(
      `Port ${BACKEND_PORT} ist bereits belegt - vermutlich laeuft das Backend schon. Ueberspringe Start (keine doppelten Prozesse).`
    );
    return { started: false };
  }

  const uvicornBin = path.join(
    ROOT,
    ".venv",
    "bin",
    process.platform === "win32" ? "uvicorn.exe" : "uvicorn"
  );
  if (!fs.existsSync(uvicornBin)) {
    logDevErr(
      `${uvicornBin} nicht gefunden. Bitte zuerst die Python-Umgebung einrichten ` +
        `(siehe README.md / scripts/setup_mac.sh) - "npm run dev" erwartet eine ` +
        "bereits vorhandene .venv mit installierten Backend-Abhaengigkeiten."
    );
    process.exit(1);
  }

  logDev(`Starte Backend (uvicorn, .venv) auf Port ${BACKEND_PORT} ...`);
  const child = spawn(
    uvicornBin,
    [
      "app.main:app",
      "--reload",
      "--host",
      "0.0.0.0",
      "--port",
      String(BACKEND_PORT),
      "--ws-ping-interval",
      "30",
      "--ws-ping-timeout",
      "120",
    ],
    {
      cwd: ROOT,
      env: process.env,
    }
  );
  pipeWithPrefix(child.stdout, "backend", COLOR.magenta);
  pipeWithPrefix(child.stderr, "backend", COLOR.magenta);
  watchForUnexpectedExit(child, "Backend");
  spawnedChildren.push({ name: "backend", child });
  return { started: true, child };
}

async function startFrontend() {
  const inUse = await isPortInUse(FRONTEND_PORT);
  if (inUse) {
    logDevWarn(
      `Port ${FRONTEND_PORT} ist bereits belegt - vermutlich laeuft das Dashboard schon. Ueberspringe Start (keine doppelten Prozesse).`
    );
    return { started: false };
  }

  if (!fs.existsSync(path.join(FRONTEND_DIR, "node_modules"))) {
    logDevErr(
      `frontend/node_modules nicht gefunden. Bitte zuerst einmalig "npm install" im ` +
        'Ordner "frontend" ausfuehren - "npm run dev" installiert keine Abhaengigkeiten.'
    );
    process.exit(1);
  }

  logDev(`Starte Dashboard (Next.js) auf Port ${FRONTEND_PORT} ...`);
  const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm";
  const child = spawn(npmCmd, ["run", "dev", "--", "-p", String(FRONTEND_PORT)], {
    cwd: FRONTEND_DIR,
    env: process.env,
  });
  pipeWithPrefix(child.stdout, "frontend", COLOR.cyan);
  pipeWithPrefix(child.stderr, "frontend", COLOR.cyan);
  watchForUnexpectedExit(child, "Frontend");
  spawnedChildren.push({ name: "frontend", child });
  return { started: true, child };
}

async function main() {
  logDev("Digital Vision Dario - lokale Entwicklungsumgebung wird gestartet ...");

  const backend = await startBackend();
  const frontend = await startFrontend();

  if (!backend.started && !frontend.started) {
    logDevOk("Backend und Dashboard laufen bereits - nichts weiter zu tun.");
    const health = await httpGetOk(HEALTH_URL);
    if (health.ok) {
      logDevOk(`Backend-Health-Check OK (${HEALTH_URL}).`);
    } else {
      logDevWarn(`Backend-Health-Check fehlgeschlagen (${HEALTH_URL}) - bitte manuell pruefen.`);
    }
    logDevOk(`Dashboard erreichbar unter ${DASHBOARD_URL}`);
    process.exit(0);
  }

  const health = await waitForHttpOk(HEALTH_URL, {
    timeoutMs: 30000,
    intervalMs: 700,
    label: "Backend-Health-Check",
  });
  if (!health.ok) {
    logDevErr(
      `Backend antwortet nach 30s nicht erfolgreich auf ${HEALTH_URL}. Breche ab ` +
        "und beende bereits gestartete Prozesse."
    );
    await shutdown(1);
    return;
  }
  logDevOk(`Backend-Health-Check OK (${HEALTH_URL}): ${health.body.trim()}`);

  if (frontend.started) {
    const ready = await waitForHttpOk(DASHBOARD_URL, {
      timeoutMs: 60000,
      intervalMs: 1000,
      label: "Dashboard (Next.js Dev-Server)",
    });
    if (!ready.ok) {
      logDevWarn(
        `Dashboard antwortet nach 60s noch nicht unter ${DASHBOARD_URL} - Next.js braucht ` +
          "beim allerersten Start manchmal laenger (Kompilierung). Laeuft im Hintergrund weiter."
      );
    } else {
      logDevOk(`Dashboard erreichbar unter ${DASHBOARD_URL}`);
    }
  } else {
    logDevOk(`Dashboard erreichbar unter ${DASHBOARD_URL}`);
  }

  logDevOk("Digital Vision Dario laeuft. Zum Beenden Ctrl+C druecken.");
}

main().catch((err) => {
  logDevErr(`Unerwarteter Fehler: ${err && err.stack ? err.stack : err}`);
  shutdown(1);
});
