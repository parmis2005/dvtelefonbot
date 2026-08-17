import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Verhindert Fehlerkennung des Projekt-Root (z.B. durch unabhaengige
  // package-lock.json-Dateien hoeher im Dateisystem) - wichtig fuer
  // reproduzierbare Builds auf Vercel.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;
