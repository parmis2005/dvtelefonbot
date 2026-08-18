#!/usr/bin/env node
/**
 * Root-Befehl fuer einen echten, bestaetigungspflichtigen Twilio-Testanruf:
 * `npm run dev`
 *
 * Der eigentliche Sicherheits-Prompt bleibt in app/twilio_test_call.py:
 * Erst wenn dort exakt "ja" eingegeben wird, wird ein kostenpflichtiger
 * Twilio-Anruf ausgeloest.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const pythonBin = path.join(
  ROOT,
  ".venv",
  process.platform === "win32" ? "Scripts" : "bin",
  process.platform === "win32" ? "python.exe" : "python"
);

if (!fs.existsSync(pythonBin)) {
  process.stderr.write(
    `[call] ${pythonBin} nicht gefunden.\n` +
      "[call] Bitte zuerst die Python-Umgebung einrichten, z.B. mit scripts/setup_mac.sh.\n"
  );
  process.exit(1);
}

const args = ["-m", "app.twilio_test_call", ...process.argv.slice(2)];
const child = spawn(pythonBin, args, {
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
  process.stderr.write(`[call] Start fehlgeschlagen: ${err.message}\n`);
  process.exit(1);
});
