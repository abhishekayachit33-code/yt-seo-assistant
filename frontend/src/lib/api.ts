import type { ReportOut } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Thin fetch wrapper for the FastAPI backend. Every authenticated screen
 * (history, analyze, ...) goes through this so the Bearer-token attachment
 * lives in one place. */
export async function apiFetch<T>(
  path: string,
  accessToken: string | undefined,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export function analyzeVideo(
  accessToken: string | undefined,
  body: { url: string; include_competitors: boolean; run_keyword_pipeline: boolean },
) {
  return apiFetch<ReportOut>("/analyze", accessToken, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function planVideo(
  accessToken: string | undefined,
  body: {
    script: string; title: string; description: string; tags: string;
    title_variant: string; include_competitors: boolean; run_keyword_pipeline: boolean;
  },
) {
  return apiFetch<ReportOut>("/plan", accessToken, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function historyReport(accessToken: string | undefined, analysisId: number) {
  return apiFetch<ReportOut>(`/history/${analysisId}/report`, accessToken);
}

export function generateThumbnails(
  accessToken: string | undefined,
  body: { title: string; context: string; count?: number },
) {
  return apiFetch<{
    concepts: {
      label: string; image_base64: string; mime_type: string;
      critique: Record<string, unknown>;
    }[];
  }>("/thumbnail/generate", accessToken, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function thumbnailCritique(
  accessToken: string | undefined,
  body: { thumbnail_url?: string; image_base64?: string; mime_type?: string },
) {
  return apiFetch<Record<string, unknown>>("/thumbnail/critique", accessToken, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function signup(email: string, password: string, displayName: string) {
  const res = await fetch(`${API_URL}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
