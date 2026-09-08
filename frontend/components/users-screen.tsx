"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";
import type { AccountUser, UserHistory } from "@/lib/users";

const fmt = (value: string | null) => value
  ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value))
  : "—";

export function UsersScreen() {
  const [users, setUsers] = useState<AccountUser[]>([]);
  const [q, setQ] = useState("");
  const [access, setAccess] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<AccountUser | null>(null);
  const [history, setHistory] = useState<UserHistory[]>([]);
  const [creditMode, setCreditMode] = useState<"add" | "set">("add");
  const [creditAmount, setCreditAmount] = useState("");
  const [trials, setTrials] = useState("");
  const [saving, setSaving] = useState(false);
  const pageSize = 25;

  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    const params = new URLSearchParams({ q, access, page: String(page), pageSize: String(pageSize) });
    const response = await fetch(`/api/users?${params}`, { cache: "no-store" });
    if (response.status === 401) { location.href = "/login"; return; }
    if (!response.ok) { setError("Could not load users."); setLoading(false); return; }
    const data = await response.json();
    setUsers(data.users); setTotal(data.total); setLoading(false);
  }, [q, access, page]);

  useEffect(() => { refresh(); }, [refresh]);

  async function open(user: AccountUser) {
    setSelected(user); setHistory([]);
    const response = await fetch(`/api/users/${user.user_id}/history`, { cache: "no-store" });
    if (response.ok) setHistory((await response.json()).history);
  }

  async function save(kind: "credits" | "trials" | "complimentary") {
    const payload: { creditMode?: "add" | "set"; creditAmount?: number; aiTrials?: number; complimentary?: boolean } = {};
    if (kind === "credits") { payload.creditMode = creditMode; payload.creditAmount = Number(creditAmount); }
    if (kind === "trials") payload.aiTrials = Number(trials);
    if (kind === "complimentary") payload.complimentary = !selected?.complimentary;
    setSaving(true);
    const response = await fetch(`/api/users/${selected?.user_id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await response.json(); setSaving(false);
    if (!response.ok) { setError(data.error || "Could not update user."); return; }
    setSelected(data.user); setCreditAmount(""); setTrials("");
    await refresh(); await open(data.user);
  }

  const pages = Math.max(1, Math.ceil(total / pageSize));
  return <AdminLayout><main className="dashboard-shell">
    <header className="topbar"><div><p className="eyebrow">Entitlements</p><h1>Users</h1><p className="page-intro">Manage credits, AI trials, subscriptions, and complimentary access with a durable audit trail.</p></div><button className="button ghost" onClick={refresh}>{loading ? "Refreshing…" : "Refresh"}</button></header>
    <section className="panel">
      <div className="filters"><input aria-label="Search users" placeholder="Username, name, or Telegram ID" value={q} onChange={(event) => setQ(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { setPage(1); refresh(); } }} /><select value={access} onChange={(event) => { setAccess(event.target.value); setPage(1); }}><option value="">All users</option><option value="free">Free</option><option value="subscribed">Subscribed</option><option value="complimentary">Complimentary</option><option value="low_credit">Low credit</option><option value="ai_exhausted">AI trials exhausted</option></select></div>
      {error && <p className="inline-error">{error}</p>}
      <div className="table-wrap"><table><thead><tr><th>User</th><th>Access</th><th>Credits</th><th>AI trials</th><th>Downloads</th><th>Referrals</th><th>Last seen</th><th /></tr></thead><tbody>{users.map((user) => <tr key={user.user_id}>
        <td><strong>{user.username || user.display_name || "Unnamed"}</strong><span className="muted">{user.user_id}</span></td>
        <td><span className={`status ${user.premium ? "status-completed" : ""}`}>{user.complimentary ? "complimentary" : user.premium ? "premium" : "free"}</span>{user.subscription_expires_at && <span className="muted">to {fmt(user.subscription_expires_at)}{user.subscription_cancelled ? " · renewal off" : ""}</span>}</td>
        <td>{user.premium ? "∞" : user.credits}<span className="muted">{user.reserved_credits} reserved</span></td><td>{user.premium ? "∞" : user.ai_trials}<span className="muted">{user.reserved_ai_trials} reserved</span></td>
        <td>{user.successful_downloads}<span className="muted">{user.successful_operations} total operations</span></td><td>{user.qualified_referrals}<span className="muted">{user.pending_referrals} pending</span>{user.suspicious_referrals > 0 && <span className="error-detail">{user.suspicious_referrals} flagged</span>}</td><td className="nowrap">{fmt(user.last_seen_at)}</td><td><button className="button ghost small-button" onClick={() => open(user)}>Manage</button></td>
      </tr>)}</tbody></table></div>
      {!loading && !users.length && <div className="empty-state"><h2>No users found</h2></div>}
      <div className="pagination"><span>Page {page} of {pages} · {total} users</span><div><button className="button ghost small-button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Previous</button><button className="button ghost small-button" disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Next</button></div></div>
    </section>
    {selected && <section className="panel user-manager"><div className="composer-heading"><div><span className="section-kicker">Manage user</span><h2>{selected.username || selected.display_name || selected.user_id}</h2></div><button className="button ghost small-button" onClick={() => setSelected(null)}>Close</button></div>
      <div className="entitlement-actions"><label>Credit balance action<select value={creditMode} onChange={(event) => setCreditMode(event.target.value as "add" | "set")}><option value="add">Top up credits</option><option value="set">Set exact balance</option></select><input type="number" min="0" max="1000000" value={creditAmount} onChange={(event) => setCreditAmount(event.target.value)} placeholder={creditMode === "add" ? "Credits to add" : "New total balance"} /><button className="button" disabled={saving || !creditAmount} onClick={() => save("credits")}>{creditMode === "add" ? "Top up" : "Set balance"}</button></label><label>Set remaining AI trials<input type="number" min="0" max="100" value={trials} onChange={(event) => setTrials(event.target.value)} /><button className="button" disabled={saving || trials === ""} onClick={() => save("trials")}>Set trials</button></label><label>Complimentary access<span className="muted">Currently {selected.complimentary ? "enabled" : "disabled"}</span><button className="button ghost" disabled={saving} onClick={() => save("complimentary")}>{selected.complimentary ? "Revoke" : "Grant"} unlimited</button></label></div>
      <h2>Audit history</h2><div className="history-list account-history">{history.map((item, index) => <article key={`${item.createdAt}-${index}`}><strong>{item.type}</strong><span>{item.reason}</span><small>{item.actor} · {fmt(item.createdAt)}</small></article>)}{!history.length && <p className="muted">No history yet.</p>}</div>
    </section>}
  </main></AdminLayout>;
}
