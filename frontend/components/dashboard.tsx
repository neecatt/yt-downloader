"use client";

import { useState } from "react";
import type { ActivityEvent, ActivityResponse } from "@/lib/activity-types";
import { formatBytes, safeUrlLabel } from "@/lib/activity-types";
import { AdminLayout } from "@/components/admin-layout";

function date(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusClass(status: string) {
  return `status status-${status}`;
}

export function Dashboard({ initialData }: { initialData: ActivityResponse | null }) {
  const [data, setData] = useState(initialData);
  const [q, setQ] = useState("");
  const [platform, setPlatform] = useState("");
  const [status, setStatus] = useState("");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const allVisibleSelected = Boolean(data?.events.length) && data!.events.every((event) => selectedIds.includes(event.id));

  async function refresh() {
    setLoading(true);
    setError("");
    const params = new URLSearchParams({ q, platform, status });
    const response = await fetch(`/api/activity?${params}`, { cache: "no-store" });
    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }
    if (!response.ok) {
      setError("Could not load activity. Check the API connection.");
      setLoading(false);
      return;
    }
    setData(await response.json());
    setSelectedIds([]);
    setLoading(false);
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
    await refresh();
    setDeleting(false);
  }

  return <AdminLayout><main className="dashboard-shell">
    <header className="topbar">
      <div><p className="eyebrow">Downloader admin</p><h1>Activity</h1></div>
      <div className="topbar-actions">
        {data?.demo && <span className="demo-badge">Demo data</span>}
        {selectedIds.length > 0 && <button className="button danger" onClick={removeSelected} disabled={deleting || data?.demo}>{deleting ? "Deleting…" : `Delete ${selectedIds.length}`}</button>}
        <button className="button ghost" onClick={refresh} disabled={loading || deleting}>{loading ? "Refreshing…" : "Refresh"}</button>
      </div>
    </header>

    <section className="stats-grid"><Stat label="Events" value={String(data?.summary.total ?? 0)} /><Stat label="Completed" value={String(data?.summary.completed ?? 0)} /><Stat label="Failed" value={String(data?.summary.failed ?? 0)} /><Stat label="Media transferred" value={formatBytes(data?.summary.totalBytes ?? 0)} /></section>

    <section className="panel">
      <div className="filters"><input aria-label="Search activity" placeholder="Search username, title, or link" value={q} onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => event.key === "Enter" && refresh()} /><select aria-label="Filter platform" value={platform} onChange={(event) => setPlatform(event.target.value)}><option value="">All platforms</option><option value="youtube">YouTube</option><option value="instagram">Instagram</option><option value="facebook">Facebook</option><option value="tiktok">TikTok</option></select><select aria-label="Filter status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="started">Started</option><option value="cancelled">Cancelled</option></select><button className="button" onClick={refresh} disabled={loading}>Apply</button></div>
      {error && <p className="inline-error">{error}</p>}
      {data?.events.length ? <div className="table-wrap"><table><thead><tr><th className="select-cell"><input type="checkbox" aria-label="Select all visible activity" checked={allVisibleSelected} onChange={toggleAll} /></th><th>User</th><th>Link / title</th><th>Format</th><th>Status</th><th>Delivery</th><th>Size</th><th>When</th></tr></thead><tbody>{data.events.map((event: ActivityEvent) => <tr key={event.id}><td className="select-cell"><input type="checkbox" aria-label={`Select activity ${event.title || event.sourceUrl}`} checked={selectedIds.includes(event.id)} onChange={() => toggleSelected(event.id)} /></td><td><strong>{event.telegramUsername || "No username"}</strong><span className="muted">{event.telegramDisplayName || "—"}</span></td><td><a href={event.sourceUrl} target="_blank" rel="noreferrer">{event.title || safeUrlLabel(event.sourceUrl)}</a>{event.error && <span className="error-detail">{event.error}</span>}</td><td>{event.platform}<span className="muted">{event.format || event.action}</span></td><td><span className={statusClass(event.status)}>{event.status}</span></td><td>{event.delivery || "—"}</td><td>{formatBytes(event.sizeBytes)}</td><td className="nowrap">{date(event.createdAt)}</td></tr>)}</tbody></table></div> : <div className="empty-state"><h2>{initialData ? "No activity found" : "Activity API not connected"}</h2><p>{initialData ? "Try another filter or refresh the dashboard." : "Set ADMIN_API_URL and connect the bot activity endpoint. Demo data can be enabled locally with DASHBOARD_DEMO=true."}</p></div>}
    </section>
    <footer className="privacy-note">Bot activity only · Telegram usernames are shown when available · user IDs are intentionally not displayed.</footer>
  </main></AdminLayout>;
}

function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div>; }
