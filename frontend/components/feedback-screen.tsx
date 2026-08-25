"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";
import type { FeedbackItem } from "@/lib/feedback";

function date(value: string) {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function FeedbackScreen() {
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [newCount, setNewCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    const response = await fetch(`/api/feedback?status=${encodeURIComponent(status)}&q=${encodeURIComponent(query)}`, { cache: "no-store" });
    if (response.status === 401) { window.location.href = "/login"; return; }
    if (!response.ok) { setError("Could not load feedback."); setLoading(false); return; }
    const data = await response.json() as { feedbacks: FeedbackItem[]; newCount: number };
    setItems(data.feedbacks); setNewCount(data.newCount); setLoading(false);
  }, [query, status]);

  useEffect(() => { refresh(); }, [refresh]);

  async function setItemStatus(item: FeedbackItem, next: "new" | "reviewed") {
    const response = await fetch(`/api/feedback/${item.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: next }) });
    if (!response.ok) { setError("Could not update feedback."); return; }
    await refresh();
  }

  async function remove(item: FeedbackItem) {
    if (!window.confirm("Delete this feedback? This cannot be undone.")) return;
    const response = await fetch(`/api/feedback/${item.id}`, { method: "DELETE" });
    if (!response.ok) { setError("Could not delete feedback."); return; }
    await refresh();
  }

  return <AdminLayout><main className="dashboard-shell">
    <header className="topbar"><div><p className="eyebrow">Product insight</p><h1>Feedback</h1><p className="page-intro">Review suggestions sent through the bot.</p></div><div className="topbar-actions"><span className="demo-badge">{newCount} new</span><button className="button ghost" onClick={refresh} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button></div></header>
    <section className="panel">
      <div className="filters"><input aria-label="Search feedback" placeholder="Search feedback or username" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && refresh()} /><select aria-label="Filter feedback status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All feedback</option><option value="new">New</option><option value="reviewed">Reviewed</option></select><button className="button" onClick={refresh} disabled={loading}>Apply</button></div>
      {error && <p className="inline-error">{error}</p>}
      {items.length ? <div className="feedback-list">{items.map((item) => <article className={`feedback-card${item.status === "new" ? " is-new" : ""}`} key={item.id}><div className="feedback-card-head"><div><strong>{item.telegramUsername || item.telegramDisplayName || "Unnamed user"}</strong><span className="muted">{item.telegramDisplayName || "—"}</span></div><span className={`status status-${item.status}`}>{item.status}</span></div><p className="feedback-text">{item.feedback}</p><div className="feedback-card-foot"><span className="muted">{date(item.createdAt)}</span><div><button className="button ghost small-button" onClick={() => setItemStatus(item, item.status === "new" ? "reviewed" : "new")}>{item.status === "new" ? "Mark reviewed" : "Mark new"}</button><button className="button danger small-button" onClick={() => remove(item)}>Delete</button></div></div></article>)}</div> : <div className="empty-state"><h2>{loading ? "Loading feedback…" : "No feedback found"}</h2><p>{loading ? "" : "Feedback sent with /feedback will appear here."}</p></div>}
    </section>
  </main></AdminLayout>;
}
