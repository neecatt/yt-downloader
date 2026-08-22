import "server-only";
import type { ActivityEvent, ActivityResponse } from "@/lib/activity-types";

export type ActivityFilters = { q?: string; platform?: string; status?: string; page?: number; pageSize?: number };
const emptyResponse: ActivityResponse = { events: [], summary: { total: 0, completed: 0, failed: 0, activeUsers: 0, totalBytes: 0 }, page: 1, pageSize: 25, total: 0 };
const demoEvents: ActivityEvent[] = [
  { id: "demo-1", telegramUsername: "@alex_demo", telegramDisplayName: "Alex", sourceUrl: "https://youtu.be/example", title: "Example video", platform: "youtube", action: "download", format: "1080p", status: "completed", delivery: "r2", sizeBytes: 128 * 1024 * 1024, durationMs: 42000, error: null, createdAt: new Date(Date.now() - 12 * 60 * 1000).toISOString() },
  { id: "demo-2", telegramUsername: null, telegramDisplayName: "No username", sourceUrl: "https://www.instagram.com/reel/example/", title: "Example reel", platform: "instagram", action: "download", format: "mp3", status: "failed", delivery: null, sizeBytes: null, durationMs: 8000, error: "The media is private or unavailable.", createdAt: new Date(Date.now() - 42 * 60 * 1000).toISOString() },
];
function demoResponse(filters: ActivityFilters): ActivityResponse { const filtered = demoEvents.filter((event) => { const query = filters.q?.toLowerCase(); return (!query || `${event.telegramUsername} ${event.title} ${event.sourceUrl}`.toLowerCase().includes(query)) && (!filters.platform || event.platform === filters.platform) && (!filters.status || event.status === filters.status); }); return { events: filtered, summary: { total: filtered.length, completed: filtered.filter((e) => e.status === "completed").length, failed: filtered.filter((e) => e.status === "failed").length, activeUsers: new Set(filtered.map((e) => e.telegramUsername ?? e.telegramDisplayName)).size, totalBytes: filtered.reduce((total, e) => total + (e.sizeBytes ?? 0), 0) }, page: 1, pageSize: filtered.length, total: filtered.length, demo: true }; }
function paramsFromFilters(filters: ActivityFilters) { const params = new URLSearchParams(); if (filters.q) params.set("q", filters.q.slice(0, 100)); if (filters.platform) params.set("platform", filters.platform); if (filters.status) params.set("status", filters.status); params.set("page", String(Math.max(1, filters.page ?? 1))); params.set("pageSize", String(Math.min(100, Math.max(1, filters.pageSize ?? 25)))); return params; }
export async function fetchActivity(filters: ActivityFilters = {}): Promise<ActivityResponse> { if (process.env.DASHBOARD_DEMO === "true") return demoResponse(filters); if (!process.env.ADMIN_API_URL) return emptyResponse; const url = new URL(process.env.ADMIN_ACTIVITY_PATH || "/admin/activity", process.env.ADMIN_API_URL); url.search = paramsFromFilters(filters).toString(); const headers: HeadersInit = { Accept: "application/json" }; if (process.env.ADMIN_API_TOKEN) headers.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`; const response = await fetch(url, { headers, cache: "no-store", signal: AbortSignal.timeout(8000) }); if (!response.ok) throw new Error(`Activity API returned ${response.status}`); const data = (await response.json()) as ActivityResponse; if (!Array.isArray(data.events) || !data.summary) throw new Error("Activity API returned an invalid response"); return data; }

export async function deleteActivity(ids: string[]) {
  if (!process.env.ADMIN_API_URL) throw new Error("Activity API is not configured");
  const url = new URL(process.env.ADMIN_ACTIVITY_PATH || "/admin/activity", process.env.ADMIN_API_URL);
  const headers: HeadersInit = { Accept: "application/json", "Content-Type": "application/json" };
  if (process.env.ADMIN_API_TOKEN) headers.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`;
  const response = await fetch(url, { method: "DELETE", headers, body: JSON.stringify({ ids }), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`Activity API returned ${response.status}`);
  return (await response.json()) as { deleted: number };
}
