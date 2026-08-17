import { api } from "@/lib/api";

export const fetcher = <T>(path: string) => api.get<T>(path);
