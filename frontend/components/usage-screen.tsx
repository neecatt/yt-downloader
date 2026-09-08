"use client";
import { useEffect, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";
import type { UsageData } from "@/lib/monetization-admin";

const labels: [string, string][] = [["users", "Total users"], ["newUsers", "New users"], ["successfulOperations", "Successful operations"], ["downloads", "Downloads"], ["aiRequests", "AI requests"], ["transcriptions", "Transcriptions"], ["summaries", "Summaries"], ["creditsSpent", "Credits spent"], ["qualifiedReferrals", "Qualified referrals"]];
export function UsageScreen() {
  const [data, setData] = useState<UsageData | null>(null); const [days, setDays] = useState(30); const [error, setError] = useState("");
  async function load() { setError(""); const response = await fetch(`/api/usage?days=${days}`, { cache: "no-store" }); if (response.status===401) { location.href="/login"; return; } if (!response.ok) { setError("Could not load usage data."); return; } setData(await response.json()); }
  useEffect(() => { load(); }, [days]);
  const max = Math.max(1, ...(data?.daily.map((item) => item.successfulOperations) || []));
  return <AdminLayout><main className="dashboard-shell"><header className="topbar"><div><p className="eyebrow">Product intelligence</p><h1>Usage dashboard</h1><p className="page-intro">Understand adoption, AI demand, referral conversion, and credit consumption before launching payments.</p></div><div className="topbar-actions"><select value={days} onChange={(event) => setDays(Number(event.target.value))}><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option></select><button className="button ghost" onClick={load}>Refresh</button></div></header>{error&&<p className="inline-error">{error}</p>}<section className="stats-grid usage-stats">{labels.map(([key,label])=><article className="stat" key={key}><span>{label}</span><strong>{data?.totals[key] ?? "—"}</strong></article>)}</section><section className="panel usage-chart"><div className="panel-heading"><div><p className="eyebrow">Activity trend</p><h2>Successful operations</h2></div><span className="muted">Daily totals</span></div><div className="bar-chart">{data?.daily.map((item)=><div className="bar-column" key={item.date}><div className="bar" style={{ height: `${Math.max(4, item.successfulOperations / max * 180)}px` }} title={`${item.successfulOperations} operations`} /><small>{item.date.slice(5)}</small></div>)}{!data?.daily.length&&<p className="muted">No completed operations in this period.</p>}</div></section></main></AdminLayout>;
}
