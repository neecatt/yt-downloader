"use client";

import { useEffect, useMemo, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";
import type { UsageData } from "@/lib/monetization-admin";

const labels: [string, string][] = [["users", "Total users"], ["newUsers", "New users"], ["successfulOperations", "Successful operations"], ["downloads", "Downloads"], ["aiRequests", "AI requests"], ["transcriptions", "Transcriptions"], ["summaries", "Summaries"], ["creditsSpent", "Credits spent"], ["qualifiedReferrals", "Qualified referrals"]];
const FILTER_STORAGE_KEY = "yt-downloader.usage-exclusions.v1";

function dateLabel(value: string) {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(`${value}T00:00:00Z`));
}

function exclusions(value: string) {
  const candidates = value.split(",").map((username) => username.trim().replace(/^@/, "").toLowerCase()).filter(Boolean);
  if (candidates.length > 50 || candidates.some((username) => !/^[a-z0-9_]{5,32}$/.test(username))) {
    throw new Error("Enter up to 50 valid Telegram usernames separated by commas.");
  }
  return [...new Set(candidates)];
}

export function UsageScreen() {
  const [data, setData] = useState<UsageData | null>(null);
  const [days, setDays] = useState(30);
  const [excludeUsers, setExcludeUsers] = useState("");
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function load(rawExclusions = excludeUsers) {
    setError("");
    try {
      const normalized = exclusions(rawExclusions);
      const params = new URLSearchParams({ days: String(days) });
      if (normalized.length) params.set("excludeUsers", normalized.join(","));
      const response = await fetch(`/api/usage?${params}`, { cache: "no-store" });
      if (response.status === 401) { location.href = "/login"; return; }
      if (!response.ok) throw new Error("Could not load usage data.");
      setData(await response.json());
      window.localStorage.setItem(FILTER_STORAGE_KEY, rawExclusions);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not load usage data.");
    }
  }

  useEffect(() => {
    const saved = window.localStorage.getItem(FILTER_STORAGE_KEY) || "";
    setExcludeUsers(saved.slice(0, 1700));
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) void load();
    // The persisted filter is loaded once; subsequent requests use current UI state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days, ready]);

  function resetExclusions() {
    setExcludeUsers("");
    window.localStorage.removeItem(FILTER_STORAGE_KEY);
    void load("");
  }

  const points = useMemo(() => {
    const daily = data?.daily || [];
    const max = Math.max(1, ...daily.map((item) => item.successfulOperations));
    return daily.map((item, index) => ({ ...item, x: daily.length <= 1 ? 50 : (index / (daily.length - 1)) * 100, y: 92 - (item.successfulOperations / max) * 76 }));
  }, [data]);
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const selected = hovered === null ? null : points[hovered];

  return <AdminLayout><main className="dashboard-shell">
    <header className="topbar"><div><p className="eyebrow">Product intelligence</p><h1>Usage dashboard</h1><p className="page-intro">Understand adoption, AI demand, referral conversion, and credit consumption before launching payments.</p></div><div className="topbar-actions"><select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select><button className="button ghost" onClick={() => load()}>Refresh</button></div></header>
    <section className="panel usage-filters"><span className="muted">Exclude test accounts from every metric and chart.</span><input aria-label="Exclude Telegram usernames" placeholder="@your_username, @test_account" value={excludeUsers} onChange={(event) => setExcludeUsers(event.target.value)} onKeyDown={(event) => event.key === "Enter" && load()} /><button className="button" onClick={() => load()}>Apply</button><button className="button ghost" onClick={resetExclusions}>Reset</button></section>
    {error && <p className="inline-error">{error}</p>}
    <section className="stats-grid usage-stats">{labels.map(([key, label]) => <article className="stat" key={key}><span>{label}</span><strong>{data?.totals[key] ?? "—"}</strong></article>)}</section>
    <section className="panel usage-chart"><div className="panel-heading"><div><p className="eyebrow">Activity trend</p><h2>Successful operations</h2></div><span className="muted">Hover a point for details</span></div>{points.length ? <div className="line-chart"><svg viewBox="0 0 100 100" role="img" aria-label="Successful operations by day" preserveAspectRatio="none"><defs><linearGradient id="usage-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity=".22" /><stop offset="100%" stopColor="var(--accent)" stopOpacity="0" /></linearGradient></defs><line x1="0" y1="92" x2="100" y2="92" className="chart-axis" /><polyline points={`${line} 100,92 0,92`} className="chart-area" /><polyline points={line} className="chart-line" />{points.map((point, index) => <circle key={point.date} cx={point.x} cy={point.y} r={hovered === index ? 1.9 : 1.25} className="chart-point" onMouseEnter={() => setHovered(index)} onMouseLeave={() => setHovered(null)} onFocus={() => setHovered(index)} onBlur={() => setHovered(null)} tabIndex={0} aria-label={`${dateLabel(point.date)}: ${point.successfulOperations} successful operations`} />)}</svg>{selected && <div className="chart-tooltip" style={{ left: `${Math.min(86, Math.max(14, selected.x))}%` }}><strong>{dateLabel(selected.date)}</strong><span>{selected.successfulOperations} operations</span><span>{selected.aiRequests} AI requests · {selected.summaries} summaries</span></div>}<div className="chart-labels"><span>{dateLabel(points[0].date)}</span><span>{dateLabel(points[Math.floor(points.length / 2)].date)}</span><span>{dateLabel(points[points.length - 1].date)}</span></div></div> : <p className="muted">No completed operations in this period.</p>}</section>
  </main></AdminLayout>;
}
