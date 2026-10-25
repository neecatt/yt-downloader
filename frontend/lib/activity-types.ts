export type ActivityStatus = "started" | "completed" | "failed" | "cancelled";
export type DeliveryMode = "telegram" | "r2" | null;
export type ActivityEvent = { id: string; telegramUsername: string | null; telegramDisplayName: string | null; sourceUrl: string; title: string | null; platform: string; action: string; format: string | null; status: ActivityStatus; delivery: DeliveryMode; sizeBytes: number | null; durationMs: number | null; error: string | null; createdAt: string };
export type ActivitySummary = { total: number; completed: number; failed: number; activeUsers: number; totalBytes: number };
export type ActivityResponse = { events: ActivityEvent[]; summary: ActivitySummary; page: number; pageSize: number; total: number; demo?: boolean };
export function formatBytes(bytes: number | null) { if (bytes === null || !Number.isFinite(bytes)) return "—"; if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`; if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`; if (bytes < 1024 ** 4) return `${(bytes / 1024 ** 3).toFixed(2)} GB`; return `${(bytes / 1024 ** 4).toFixed(2)} TB`; }
// Keep each part intact so a narrow column wraps only between the date and the time.
const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const timeFormat = new Intl.DateTimeFormat(undefined, { timeStyle: "short" });
export function formatDateTime(value: string | null | undefined) { if (!value) return "—"; const date = new Date(value); return `${dateFormat.format(date).replace(/ /g, "\u00a0")} ${timeFormat.format(date).replace(/ /g, "\u00a0")}`; }
export function formatCount(value: number | null | undefined) { return value === null || value === undefined ? "—" : value.toLocaleString("en-US"); }
export function safeUrlLabel(value: string) { try { const url = new URL(value); return `${url.hostname}${url.pathname}`.slice(0, 80); } catch { return value.slice(0, 80); } }
export function safeExternalUrl(value: string) { try { const url = new URL(value); return url.protocol === "https:" ? url.toString() : null; } catch { return null; } }
