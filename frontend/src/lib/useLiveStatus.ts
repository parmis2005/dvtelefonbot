"use client";

import { useEffect, useRef, useState } from "react";
import type { ActiveCallStatus } from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const WS_URL = API_BASE_URL.replace(/^http/, "ws") + "/ws/live-status";

/**
 * Live-Status ohne Neuladen der Seite (siehe api/live_status.py). Das
 * Backend sendet alle 1.5s die aktuell aktiven Anrufe; hier nur Empfang +
 * automatischer Reconnect bei Verbindungsabbruch.
 */
export function useLiveStatus(): { calls: ActiveCallStatus[]; connected: boolean } {
  const [calls, setCalls] = useState<ActiveCallStatus[]>([]);
  const [connected, setConnected] = useState(false);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let cancelled = false;

    function connect() {
      socket = new WebSocket(WS_URL);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data) as { active_calls: ActiveCallStatus[] };
          setCalls(payload.active_calls);
        } catch {
          // ignore malformed frame
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!cancelled) {
          retryRef.current = setTimeout(connect, 2000);
        }
      };
      socket.onerror = () => socket?.close();
    }

    connect();

    return () => {
      cancelled = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      socket?.close();
    };
  }, []);

  return { calls, connected };
}
