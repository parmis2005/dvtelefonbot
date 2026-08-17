"use client";

import useSWR, { type SWRConfiguration } from "swr";
import type { TelephonyStatus } from "@/lib/types";
import { fetcher } from "@/lib/swr";

const DEFAULT_OPTIONS: SWRConfiguration<TelephonyStatus> = {
  refreshInterval: 30000,
  dedupingInterval: 15000,
  focusThrottleInterval: 15000,
  revalidateOnFocus: false,
};

export function useTelephonyStatus(options?: SWRConfiguration<TelephonyStatus>) {
  return useSWR<TelephonyStatus>("/api/telephony/status", fetcher, {
    ...DEFAULT_OPTIONS,
    ...options,
  });
}
