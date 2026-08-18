#!/usr/bin/env node
/**
 * Root-Befehl fuer einen echten, bestaetigungspflichtigen Twilio-Testanruf:
 * `npm run dev`
 *
 * Startet bei Bedarf automatisch:
 * - Backend auf Port 8000
 * - ngrok-Tunnel auf Port 8000
 *
 * Danach startet es app.twilio_test_call.py. Ohne --yes wird erst bei exakt
 * "ja" im Prompt ein kostenpflichtiger Twilio-Anruf ausgeloest. Mit
 * `npm run dev -- --yes` gilt diese Bestaetigung als explizit erteilt.
 */

"use strict";

const fs = require("fs");
const http = require("http");
const net = require("net");
const path = require("path");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const BACKEND_PORT = 8000;
const NGROK_API_URL = "http://127.0.0.1:4040/api/tunnels";
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/api/health`;
const argsFromCli = process.argv.slice(2);

const COLOR = {
  reset: "\x1b[0m",
  dim: "\x1b[2m",
  cyan: "\x1b[36m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  red: "\x1b[31m",
};

const pythonBin = path.join(
  ROOT,
  ".venv",
  process.platform === "win32" ? "Scripts" : "bin",
  process.platform === "win32" ? "python.exe" : "python"
);
const uvicornBin = path.join(
  ROOT,
  ".venv",
  "bin",
  process.platform === "win32" ? "uvicorn.exe" : "uvicorn"
);

const spawnedChildren = [];
let shuttingDown = false;

function log(prefix, color, message) {
  process.stdout.write(`${color}[${prefix}]${COLOR.reset} ${message}\n`);
}

const logCall = (msg) => log("call", COLOR.cyan, msg);
const logOk = (msg) => log("call", COLOR.green, msg);
const logWarn = (msg) => log("call", COLOR.yellow, msg);
const logErr = (msg) => log("call", COLOR.red, msg);

function ensurePython() {
  if (!fs.existsSync(pythonBin)) {
    logErr(`${pythonBin} nicht gefunden.`);
    logErr("Bitte zuerst die Python-Umgebung einrichten, z.B. mit scripts/setup_mac.sh.");
    process.exit(1);
  }
}

function isHelpOnly() {
  return argsFromCli.includes("--help") || argsFromCli.includes("-h");
}

function runPythonDirect() {
  const child = spawn(pythonBin, ["-m", "app.twilio_test_call", ...argsFromCli], {
    cwd: ROOT,
    env: process.env,
    stdio: "inherit",
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
  child.on("error", (err) => {
    logErr(`Start fehlgeschlagen: ${err.message}`);
    process.exit(1);
  });
}

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

function httpGet(url) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: 2000 }, (res) => {
      let body = "";
      res.on("data", (chunk) => {
        body += chunk.toString();
      });
      res.on("end", () => resolve({ ok: res.statusCode === 200, body }));
    });
    req.on("timeout", () => req.destroy());
    req.on("error", () => resolve({ ok: false, body: "" }));
  });
}

async function waitFor(description, timeoutMs, intervalMs, fn) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const result = await fn();
    if (result) return result;
    if (Date.now() > deadline) return null;
    logCall(`Warte auf ${description} ...`);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

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

function killChild(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.killed) return resolve();
    const forceKillTimer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        /* Prozess bereits beendet */
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

async function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  const ownChildren = [...spawnedChildren].reverse();
  if (ownChildren.length > 0) {
    logCall("Beende automatisch gestartete Prozesse ...");
    await Promise.all(ownChildren.map(({ child }) => killChild(child)));
  }
  process.exit(code);
}

process.on("SIGINT", () => {
  logCall("Ctrl+C erkannt.");
  shutdown(0);
});
process.on("SIGTERM", () => shutdown(0));

async function findNgrokTunnel() {
  const response = await httpGet(NGROK_API_URL);
  if (!response.ok) return null;

  let payload;
  try {
    payload = JSON.parse(response.body);
  } catch {
    return null;
  }

  const tunnels = Array.isArray(payload.tunnels) ? payload.tunnels : [];
  const httpsTunnels = tunnels.filter((tunnel) => {
    const publicUrl = String(tunnel.public_url || "");
    if (!publicUrl.startsWith("https://")) return false;
    const addr = String((tunnel.config && tunnel.config.addr) || "");
    return addr.includes(`:${BACKEND_PORT}`) || addr.endsWith(String(BACKEND_PORT));
  });

  const tunnel = httpsTunnels[0];
  return tunnel ? String(tunnel.public_url).replace(/\/$/, "") : null;
}

async function startNgrok() {
  const existing = await findNgrokTunnel();
  if (existing) {
    logOk(`ngrok laeuft bereits: ${existing}`);
    return { publicUrl: existing, started: false };
  }

  logCall(`Starte ngrok fuer Port ${BACKEND_PORT} ...`);
  const child = spawn("ngrok", ["http", String(BACKEND_PORT)], {
    cwd: ROOT,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  spawnedChildren.push({ name: "ngrok", child });
  pipeWithPrefix(child.stdout, "ngrok", COLOR.dim);
  pipeWithPrefix(child.stderr, "ngrok", COLOR.dim);

  let spawnError = null;
  child.once("error", (err) => {
    spawnError = err;
  });
  child.once("exit", (code, signal) => {
    if (!shuttingDown && !spawnError) {
      logErr(`ngrok wurde beendet (code=${code}, signal=${signal}).`);
    }
  });

  const publicUrl = await waitFor("ngrok-Tunnel", 30000, 700, async () => {
    if (spawnError) {
      throw spawnError;
    }
    return await findNgrokTunnel();
  });
  if (!publicUrl) {
    logErr("ngrok-Tunnel wurde nach 30s nicht bereit.");
    logErr("Pruefe, ob ngrok installiert und dein ngrok-Authtoken eingerichtet ist.");
    await shutdown(1);
    return null;
  }

  logOk(`ngrok bereit: ${publicUrl}`);
  return { publicUrl, started: true };
}

async function startBackend(publicUrl) {
  const portInUse = await isPortInUse(BACKEND_PORT);
  if (portInUse) {
    const health = await httpGet(HEALTH_URL);
    if (health.ok) {
      logOk(`Backend laeuft bereits (${HEALTH_URL}).`);
      return { started: false };
    }
    logErr(`Port ${BACKEND_PORT} ist belegt, aber ${HEALTH_URL} antwortet nicht korrekt.`);
    logErr("Bitte den blockierenden Prozess beenden oder den Port freimachen.");
    await shutdown(1);
    return null;
  }

  if (!fs.existsSync(uvicornBin)) {
    logErr(`${uvicornBin} nicht gefunden.`);
    logErr("Bitte zuerst die Python-Umgebung einrichten, z.B. mit scripts/setup_mac.sh.");
    await shutdown(1);
    return null;
  }

  logCall(`Starte Backend auf Port ${BACKEND_PORT} ...`);
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
      "--proxy-headers",
    ],
    {
      cwd: ROOT,
      env: { ...process.env, TWILIO_PUBLIC_BASE_URL: publicUrl },
      stdio: ["ignore", "pipe", "pipe"],
    }
  );
  spawnedChildren.push({ name: "backend", child });
  pipeWithPrefix(child.stdout, "backend", COLOR.cyan);
  pipeWithPrefix(child.stderr, "backend", COLOR.cyan);

  child.once("exit", (code, signal) => {
    if (!shuttingDown) {
      logErr(`Backend wurde beendet (code=${code}, signal=${signal}).`);
      shutdown(1);
    }
  });

  const health = await waitFor("Backend-Health-Check", 30000, 700, async () => {
    const response = await httpGet(HEALTH_URL);
    return response.ok ? response : null;
  });
  if (!health) {
    logErr(`Backend antwortet nach 30s nicht auf ${HEALTH_URL}.`);
    await shutdown(1);
    return null;
  }

  logOk(`Backend bereit: ${health.body.trim()}`);
  return { started: true };
}

function runTestCall(publicUrl) {
  return new Promise((resolve) => {
    let callTriggered = false;
    let outputTail = "";
    const child = spawn(pythonBin, ["-m", "app.twilio_test_call", ...argsFromCli], {
      cwd: ROOT,
      env: { ...process.env, TWILIO_PUBLIC_BASE_URL: publicUrl },
      stdio: ["inherit", "pipe", "pipe"],
    });

    function forwardAndTrack(stream, target) {
      stream.on("data", (chunk) => {
        const text = chunk.toString();
        outputTail = (outputTail + text).slice(-500);
        if (outputTail.includes("Anruf ausgeloest.")) {
          callTriggered = true;
        }
        target.write(text);
      });
    }

    forwardAndTrack(child.stdout, process.stdout);
    forwardAndTrack(child.stderr, process.stderr);

    child.on("exit", (code, signal) => resolve({ code: code ?? 1, signal, callTriggered }));
    child.on("error", (err) => {
      logErr(`Testanruf-Prozess konnte nicht gestartet werden: ${err.message}`);
      resolve({ code: 1, signal: null, callTriggered: false });
    });
  });
}

async function main() {
  ensurePython();
  if (isHelpOnly()) {
    runPythonDirect();
    return;
  }

  if (argsFromCli.includes("--yes")) {
    logWarn("--yes erkannt: der Testanruf wird nach erfolgreichen Checks ohne Terminal-Prompt ausgeloest.");
  }

  logCall("Bereite echten Twilio-Testanruf vor ...");
  const ngrok = await startNgrok();
  if (!ngrok) return;
  await startBackend(ngrok.publicUrl);

  logOk(`Aktuelle oeffentliche URL fuer diesen Lauf: ${ngrok.publicUrl}`);
  logCall(
    argsFromCli.includes("--yes")
      ? "Starte explizit bestaetigten Testanruf ..."
      : "Starte bestaetigungspflichtigen Testanruf-Prompt ..."
  );
  const result = await runTestCall(ngrok.publicUrl);

  if (result.signal) {
    await shutdown(1);
    return;
  }

  if (!result.callTriggered) {
    await shutdown(result.code);
    return;
  }

  logOk("Anruf wurde ausgeloest.");
  logWarn("Backend und ngrok bleiben jetzt aktiv, damit Dario im laufenden Call antworten kann.");
  logWarn("Nach dem Telefonat hier Ctrl+C druecken, um automatisch gestartete Prozesse zu beenden.");
}

main().catch(async (err) => {
  logErr(`Unerwarteter Fehler: ${err && err.stack ? err.stack : err}`);
  await shutdown(1);
});
