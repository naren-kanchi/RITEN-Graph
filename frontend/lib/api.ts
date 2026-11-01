"use client";
import { useCallback, useEffect, useState } from "react";

export type Row = Record<string, any>;
export type Page = { items: Row[]; total: number; limit: number; offset: number };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function messageFrom(body: any, status: number): string {
  if (typeof body?.detail === "string") return body.detail;
  if (Array.isArray(body?.detail)) {
    return body.detail.map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
  }
  return `Request failed (${status}).`;
}

export async function api<T = any>(path: string, init?: { method?: string; body?: unknown; signal?: AbortSignal }): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: init?.method ?? "GET",
    headers: init?.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    signal: init?.signal,
    credentials: "same-origin",
  });
  if (response.status === 401 && !path.startsWith("/auth/login")) {
    window.location.assign("/login");
    throw new ApiError(401, "Sign in to continue.");
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, messageFrom(body, response.status));
  return body as T;
}

export function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function useApi<T = any>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (path === null) {
      setData(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api<T>(path, { signal: controller.signal })
      .then((result) => {
        setData(result);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        setError(err.message ?? "Request failed.");
        setData(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [path, tick]);

  return { data, error, loading, reload };
}

const SESSION_KEY = "riten_nav_session";

function navSession(): string {
  try {
    let id = sessionStorage.getItem(SESSION_KEY);
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem(SESSION_KEY, id);
    }
    return id;
  } catch {
    return "ephemeral-session";
  }
}

/** Anonymous navigation signal for the prefetch worker. A failure here never affects the page. */
export function recordNavigation(viewType: "actor_profile" | "graph_neighborhood", entityKey: string) {
  api("/events/navigation", {
    method: "POST",
    body: { session_id: navSession(), view_type: viewType, entity_key: entityKey, client_event_id: crypto.randomUUID() },
  }).catch(() => undefined);
}

export const fmt = {
  usdM(value: number | null | undefined): string {
    if (value === null || value === undefined) return "–";
    const v = Number(value);
    if (Math.abs(v) >= 1000) return `$${(v / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}bn`;
    return `$${v.toLocaleString(undefined, { maximumFractionDigits: 1 })}m`;
  },
  usdBn(value: number | null | undefined): string {
    if (value === null || value === undefined) return "–";
    return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}bn`;
  },
  num(value: number | null | undefined, digits = 2): string {
    if (value === null || value === undefined) return "–";
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
  },
  label(value: string | null | undefined): string {
    return (value ?? "").replaceAll("_", " ");
  },
  date(value: string | null | undefined): string {
    if (!value) return "–";
    return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  },
};
