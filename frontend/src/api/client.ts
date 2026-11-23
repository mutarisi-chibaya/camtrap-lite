/** Typed API client. All requests go through Vite's /api proxy to FastAPI. */

const BASE = "/api";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return (await res.json()) as T;
}

export interface Health {
  status: string;
}

export const getHealth = () => apiGet<Health>("/health");
