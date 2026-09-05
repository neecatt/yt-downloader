"use client";

import { useEffect, useState } from "react";
import type { ActivityEvent, ActivityResponse } from "@/lib/activity-types";
import { formatBytes, safeExternalUrl, safeUrlLabel } from "@/lib/activity-types";
import { AdminLayout } from "@/components/admin-layout";

function date(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusClass(status: string) {
  return `status status-${status}`;
}

type SavedFilters = { q: string; platform: string; status: string; action: string; excludeUsers: string; preset: string };
const FILTER_STORAGE_KEY = "yt-downloader.activity-filters.v1";
const EMPTY_FILTERS: SavedFilters = { q: "", platform: "", status: "", action: "", excludeUsers: "", preset: "all" };

function exclusions(value: string) {
  const candidates = value.split(",").map((username) => username.trim().replace(/^@/, "").toLowerCase()).filter(Boolean);
  if (candidates.length > 50 || candidates.some((username) => !/^[a-z0-9_]{5,32}$/.test(username))) {
    throw new Error("Enter up to 50 valid Telegram usernames separated by commas.");
  }
  return [...new Set(candidates)];
}

export function Dashboard({ initialData }: { initialData: ActivityResponse | null }) {
  const [data, setData] = useState(initialData);
  const [q, setQ] = useState("");
  const [platform, setPlatform] = useState("");
  const [status, setStatus] = useState("");
  const [action, setAction] = useState("");
  const [excludeUsers, setExcludeUsers] = useState("");
  const [preset, setPreset] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const allVisibleSelected = Boolean(data?.events.length) && data!.events.every((event) => selectedIds.includes(event.id));
  const currentPage = data?.page ?? 1;
  const pageSize = data?.pageSize || 25;
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / pageSize));

  function currentFilters(): SavedFilters {
    return { q, platform, status, action, excludeUsers, preset };
  }

  async function refresh(page = currentPage, filters = currentFilters()) {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ q: filters.q, platform: filters.platform, status: filters.status, action: filters.action, excludeUsers: exclusions(filters.excludeUsers).join(","), page: String(page), pageSize: String(pageSize) });
      const response = await fetch(`/api/activity?${params}`, { cache: "no-store" });
      if (response.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (!response.ok) throw new Error("Activity request failed");
      setData(await response.json());
      setSelectedIds([]);
      window.localStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(filters));
    } catch (requestError) {
      const validationMessage = requestError instanceof Error && requestError.message.startsWith("Enter up to 50") ? requestError.message : null;
      setError(validationMessage || "Could not load activity. Check the API connection.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(FILTER_STORAGE_KEY) || "null") as Partial<SavedFilters> | null;
      if (!saved) return;
      const filters: SavedFilters = {
        q: typeof saved.q === "string" ? saved.q.slice(0, 100) : "",
        platform: typeof saved.platform === "string" ? saved.platform : "",
        status: typeof saved.status === "string" ? saved.status : "",
        action: typeof saved.action === "string" ? saved.action : "",
        excludeUsers: typeof saved.excludeUsers === "string" ? saved.excludeUsers.slice(0, 1700) : "",
        preset: typeof saved.preset === "string" ? saved.preset : "all",
      };
      setQ(filters.q); setPlatform(filters.platform); setStatus(filters.status); setAction(filters.action); setExcludeUsers(filters.excludeUsers); setPreset(filters.preset);
      void refresh(1, filters);
    } catch {
      window.localStorage.removeItem(FILTER_STORAGE_KEY);
    }
    // Saved filters are intentionally loaded only once when the dashboard mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function choosePreset(value: string) {
    setPreset(value);
    setPlatform(value === "youtube" ? "youtube" : "");
    setStatus(value === "completed" ? "completed" : value === "failed" ? "failed" : value === "active" ? "started" : "");
    setAction(value === "downloads" ? "download" : value === "transcripts" ? "transcript" : value === "summaries" ? "summary" : "");
  }

  function resetFilters() {
    setQ(""); setPlatform(""); setStatus(""); setAction(""); setExcludeUsers(""); setPreset("all");
    window.localStorage.removeItem(FILTER_STORAGE_KEY);
    void refresh(1, EMPTY_FILTERS);
  }

  function toggleSelected(id: string) {
    setSelectedIds((current) => current.includes(id) ? current.filter((selected) => selected !== id) : [...current, id]);
  }

  function toggleAll() {
    if (!data) return;
    setSelectedIds(allVisibleSelected ? [] : data.events.map((event) => event.id));
  }

  async function removeSelected() {
    if (!selectedIds.length || data?.demo) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected log${selectedIds.length === 1 ? "" : "s"}? This cannot be undone.`)) return;

    setDeleting(true);
    setError("");
    const response = await fetch("/api/activity", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: selectedIds }),
    });
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (!response.ok) {
      setError("Could not delete the selected logs.");
      setDeleting(false);
      return;
    }
    setSelectedIds([]);
    await refresh(currentPage);
    setDeleting(false);
  }

  return <AdminLayout><main className="dashboard-shell">
    <header className="topbar">
      <div><p className="eyebrow">Downloader admin</p><h1>Activity</h1></div>
      <div className="topbar-actions">
        {data?.demo && <span className="demo-badge">Demo data</span>}
        {selectedIds.length > 0 && <button className="button danger" onClick={removeSelected} disabled={deleting || data?.demo}>{deleting ? "Deleting…" : `Delete ${selectedIds.length}`}</button>}
        <button className="button ghost" onClick={() => refresh(currentPage)} disabled={loading || deleting}>{loading ? "Refreshing…" : "Refresh"}</button>
      </div>
    </header>

    <section className="stats-grid"><Stat label="Events" value={String(data?.summary.total ?? 0)} /><Stat label="Completed" value={String(data?.summary.completed ?? 0)} /><Stat label="Failed" value={String(data?.summary.failed ?? 0)} /><Stat label="Media transferred" value={formatBytes(data?.summary.totalBytes ?? 0)} /></section>

    <section className="panel">
      <div className="filters activity-filters"><select aria-label="Quick filter" value={preset} onChange={(event) => choosePreset(event.target.value)}><option value="all">All activity</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="active">In progress</option><option value="downloads">Downloads</option><option value="transcripts">Transcriptions</option><option value="summaries">Summaries</option><option value="youtube">YouTube</option><option value="custom">Custom</option></select><input aria-label="Search activity" placeholder="Search username, title, or link" value={q} onChange={(event) => { setQ(event.target.value); setPreset("custom"); }} onKeyDown={(event) => event.key === "Enter" && refresh(1)} /><select aria-label="Filter platform" value={platform} onChange={(event) => { setPlatform(event.target.value); setPreset("custom"); }}><option value="">All platforms</option><option value="youtube">YouTube</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="tiktok">TikTok</option><option value="x">X</option><option value="linkedin">LinkedIn</option></select><select aria-label="Filter status" value={status} onChange={(event) => { setStatus(event.target.value); setPreset("custom"); }}><option value="">All statuses</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="started">Started</option><option value="cancelled">Cancelled</option></select><input className="exclude-users" aria-label="Exclude Telegram usernames" placeholder="Exclude: @alice, @bob" value={excludeUsers} onChange={(event) => { setExcludeUsers(event.target.value); setPreset("custom"); }} onKeyDown={(event) => event.key === "Enter" && refresh(1)} /><button className="button" onClick={() => refresh(1)} disabled={loading}>Apply</button><button className="button ghost" onClick={resetFilters} disabled={loading}>Reset</button></div>
      {error && <p className="inline-error">{error}</p>}
      {data?.events.length ? <><div className="table-wrap"><table><thead><tr><th className="select-cell"><input type="checkbox" aria-label="Select all visible activity" checked={allVisibleSelected} onChange={toggleAll} /></th><th>User</th><th>Link / title</th><th>Format</th><th>Status</th><th>Delivery</th><th>Size</th><th>When</th></tr></thead><tbody>{data.events.map((event: ActivityEvent) => { const externalUrl = safeExternalUrl(event.sourceUrl); return <tr key={event.id}><td className="select-cell"><input type="checkbox" aria-label={`Select activity ${event.title || event.sourceUrl}`} checked={selectedIds.includes(event.id)} onChange={() => toggleSelected(event.id)} /></td><td><strong>{event.telegramUsername || event.telegramDisplayName || "Unknown Telegram user"}</strong>{event.telegramUsername && <span className="muted">{event.telegramDisplayName || "—"}</span>}</td><td>{externalUrl ? <a href={externalUrl} target="_blank" rel="noopener noreferrer">{event.title || safeUrlLabel(event.sourceUrl)}</a> : <span>{event.title || "Invalid source URL"}</span>}{event.error && <span className="error-detail">{event.error}</span>}</td><td>{event.platform}<span className="muted">{event.format || event.action}</span></td><td><span className={statusClass(event.status)}>{event.status}</span></td><td>{event.delivery || "—"}</td><td>{formatBytes(event.sizeBytes)}</td><td className="nowrap">{date(event.createdAt)}</td></tr>; })}</tbody></table></div><nav className="pagination" aria-label="Activity pagination"><span>Page {currentPage} of {totalPages} · {data.total} events</span><div><button className="button ghost" onClick={() => refresh(currentPage - 1)} disabled={loading || currentPage <= 1}>Previous</button><button className="button ghost" onClick={() => refresh(currentPage + 1)} disabled={loading || currentPage >= totalPages}>Next</button></div></nav></> : <div className="empty-state"><h2>{initialData ? "No activity found" : "Activity API not connected"}</h2><p>{initialData ? "Try another filter or refresh the dashboard." : "Set ADMIN_API_URL and connect the bot activity endpoint. Demo data can be enabled locally with DASHBOARD_DEMO=true."}</p></div>}
    </section>
    <footer className="privacy-note">Bot activity only · Telegram usernames are shown when available · user IDs are intentionally not displayed.</footer>
  </main></AdminLayout>;
}

function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div>; }
