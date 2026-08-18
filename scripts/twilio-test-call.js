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
const readline = require("readline");
const { execFileSync, spawn } = require("child_process");

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

function parseJson(body) {
  try {
    return JSON.parse(body);
  } catch {
    return null;
  }
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

function getListeningPids(port) {
  try {
    const output = execFileSync("lsof", [`-tiTCP:${port}`, "-sTCP:LISTEN"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return [
      ...new Set(
        output
          .split(/\s+/)
          .filter(Boolean)
          .map((pid) => Number(pid))
          .filter(Boolean)
      ),
    ];
  } catch {
    return [];
  }
}

function getProcessCommand(pid) {
  try {
    return execFileSync("ps", ["-p", String(pid), "-o", "command="], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

function isProjectBackendProcess(pid) {
  const command = getProcessCommand(pid);
  return command.includes(ROOT) || (command.includes("uvicorn") && command.includes("app.main:app"));
}

async function waitForPortFree(port, timeoutMs = 10000) {
  return await waitFor(`Port ${port} wird frei`, timeoutMs, 500, async () => {
    return (await isPortInUse(port)) ? null : true;
  });
}

async function stopExistingBackendIfSafe(reason) {
  const pids = getListeningPids(BACKEND_PORT);
  if (pids.length === 0) return true;

  const commands = new Map(pids.map((pid) => [pid, getProcessCommand(pid)]));
  const hasProjectBackend = [...commands.values()].some(
    (command) => command.includes(ROOT) || (command.includes("uvicorn") && command.includes("app.main:app"))
  );
  const unsafe = pids.filter((pid) => {
    const command = commands.get(pid) || "";
    if (isProjectBackendProcess(pid)) return false;
    if (hasProjectBackend && command.includes("Python") && command.includes("multiprocessing-fork")) {
      return false;
    }
    return true;
  });
  if (unsafe.length > 0) {
    logErr(`Port ${BACKEND_PORT} ist von einem fremden Prozess belegt: ${unsafe.join(", ")}`);
    logErr("Ich beende fremde Prozesse nicht automatisch.");
    return false;
  }

  logWarn(`${reason} Beende alte Backend-Prozesse auf Port ${BACKEND_PORT}: ${pids.join(", ")}`);
  for (const pid of pids) {
    try {
      process.kill(pid, "SIGTERM");
    } catch {
      /* Prozess bereits beendet */
    }
  }

  if (await waitForPortFree(BACKEND_PORT)) return true;

  logWarn(`Port ${BACKEND_PORT} ist noch belegt. Erzwinge Beenden der alten Backend-Prozesse.`);
  for (const pid of pids) {
    try {
      process.kill(pid, "SIGKILL");
    } catch {
      /* Prozess bereits beendet */
    }
  }

  return Boolean(await waitForPortFree(BACKEND_PORT, 5000));
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
      const payload = parseJson(health.body);
      const sourceRoot = payload && payload.runtime && payload.runtime.source_root;
      if (sourceRoot === ROOT) {
        logOk(`Backend laeuft bereits mit aktuellem Projektcode (${HEALTH_URL}).`);
        return { started: false };
      }
      const stopped = await stopExistingBackendIfSafe(
        "Backend laeuft bereits, liefert aber keine aktuelle Runtime-Kennung."
      );
      if (!stopped) {
        await shutdown(1);
        return null;
      }
    } else {
      const stopped = await stopExistingBackendIfSafe(
        `Port ${BACKEND_PORT} ist belegt, aber ${HEALTH_URL} antwortet nicht korrekt.`
      );
      if (!stopped) {
        await shutdown(1);
        return null;
      }
    }
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

function runTestCall(publicUrl, callArgs = argsFromCli) {
  return new Promise((resolve) => {
    const childArgs = ["-u", "-m", "app.twilio_test_call", ...callArgs];
    const child = spawn(pythonBin, childArgs, {
      cwd: ROOT,
      env: { ...process.env, TWILIO_PUBLIC_BASE_URL: publicUrl },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stderr = "";
    child.stdout.on("data", (chunk) => {
      process.stdout.write(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("exit", (code, signal) => {
      const exitCode = code ?? 1;
      if (stderr.trim() && signal !== "SIGINT") {
        process.stderr.write(stderr);
      }
      resolve({ code: exitCode === 2 ? 0 : exitCode, signal, callTriggered: exitCode === 2 });
    });
    child.on("error", (err) => {
      logErr(`Testanruf-Prozess konnte nicht gestartet werden: ${err.message}`);
      resolve({ code: 1, signal: null, callTriggered: false });
    });
  });
}

function needsNodeConfirmation() {
  return !argsFromCli.includes("--yes") && !argsFromCli.includes("--no-call");
}

function withoutFlags(args, flags) {
  return args.filter((arg) => !flags.includes(arg));
}

function withFlag(args, flag) {
  if (args.includes(flag)) {
    return args;
  }
  return [...args, flag];
}

function askForConfirmation() {
  if (!process.stdin.isTTY) {
    logErr("Keine interaktive Eingabe verfuegbar. Kein Anruf ausgeloest.");
    logErr("Wenn du bewusst ohne Prompt starten willst: npm run dev -- --yes");
    return Promise.resolve(false);
  }

  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: true,
    });

    rl.question(
      "\nDieser Anruf ist ECHT und KOSTENPFLICHTIG. Jetzt wirklich anrufen? Tippe 'ja' zum Bestaetigen: ",
      (answer) => {
        rl.close();
        resolve(String(answer || "").trim().toLowerCase() === "ja");
      }
    );
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
  if (argsFromCli.includes("--no-call") || argsFromCli.includes("--prepare-only")) {
    logCall(argsFromCli.includes("--prepare-only") ? "Starte Vorbereitung ohne Anruf ..." : "Starte Checks ohne Anruf ...");
    const result = await runTestCall(ngrok.publicUrl);

    if (result.signal) {
      await shutdown(1);
      return;
    }
    await shutdown(result.code);
    return;
  }

  logCall("Pruefe System und bereite Begruessung vor - noch kein Anruf ...");
  const prepareArgs = [
    ...withoutFlags(argsFromCli, ["--yes", "--prepare-only", "--skip-greeting-prep"]),
    "--prepare-only",
  ];
  const prepareResult = await runTestCall(ngrok.publicUrl, prepareArgs);

  if (prepareResult.signal) {
    await shutdown(1);
    return;
  }
  if (prepareResult.code !== 0) {
    await shutdown(prepareResult.code);
    return;
  }

  if (needsNodeConfirmation()) {
    const confirmed = await askForConfirmation();
    if (!confirmed) {
      logCall("Abgebrochen - kein Anruf ausgeloest.");
      await shutdown(0);
      return;
    }
  }

  let callArgs = withoutFlags(argsFromCli, ["--prepare-only", "--skip-greeting-prep"]);
  callArgs = withFlag(callArgs, "--yes");
  callArgs = withFlag(callArgs, "--skip-greeting-prep");

  logCall("Starte vorbereiteten Twilio-Testanruf jetzt ...");
  const result = await runTestCall(ngrok.publicUrl, callArgs);

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
