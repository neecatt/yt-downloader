"use client";

import { useEffect, useState } from "react";
import { AdminLayout } from "@/components/admin-layout";
import type { MonetizationSettings, MonetizationSettingsAudit } from "@/lib/settings";

const defaults: MonetizationSettings = {
  enabled: false,
  premiumEnabled: false,
  starterCredits: 100,
  aiCreditCost: 5,
  dailyDownloadLimit: 15,
  aiTrials: 2,
  referralInviterReward: 10,
  referralInviteeReward: 5,
  referralRequiredDownloads: 1,
  referralMonthlyCap: 5,
  premiumPriceStars: 149,
  staleReservationSeconds: 7200,
  costAlertFileMb: 1024,
  rolloutPercent: 100,
  rolloutUserIds: [],
  emergencyDisabled: false,
};

type NumericSetting = Exclude<keyof MonetizationSettings, "enabled" | "premiumEnabled" | "rolloutUserIds" | "emergencyDisabled">;

function changedSummary(changed: Record<string, unknown>) {
  const entries = Object.entries(changed).slice(0, 3).map(([key, value]) => `${key.replace(/[A-Z]/g, (letter) => ` ${letter.toLowerCase()}`)}: ${String(value)}`);
  return entries.join(" · ") || "Settings updated";
}

export function SettingsScreen() {
  const [value, setValue] = useState(defaults);
  const [history, setHistory] = useState<MonetizationSettingsAudit[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function loadHistory() {
    const response = await fetch("/api/settings/monetization/history", { cache: "no-store" });
    if (response.ok) setHistory((await response.json()).history);
  }

  useEffect(() => {
    Promise.all([
      fetch("/api/settings/monetization", { cache: "no-store" }),
      fetch("/api/settings/monetization/history", { cache: "no-store" }),
    ]).then(async ([response, historyResponse]) => {
      if (response.status === 401) { location.href = "/login"; return; }
      if (!response.ok || !historyResponse.ok) throw new Error("Could not load settings");
      setValue(await response.json());
      setHistory((await historyResponse.json()).history);
    }).catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load settings"))
      .finally(() => setLoading(false));
  }, []);

  function setNumber(name: NumericSetting, raw: string) {
    setValue((current) => ({ ...current, [name]: Number(raw) }));
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true); setError(""); setMessage("");
    try {
      const payload = {
        enabled: value.enabled,
        premiumEnabled: value.premiumEnabled,
        starterCredits: value.starterCredits,
        aiCreditCost: value.aiCreditCost,
        dailyDownloadLimit: value.dailyDownloadLimit,
        aiTrials: value.aiTrials,
        referralInviterReward: value.referralInviterReward,
        referralInviteeReward: value.referralInviteeReward,
        referralRequiredDownloads: value.referralRequiredDownloads,
        referralMonthlyCap: value.referralMonthlyCap,
        premiumPriceStars: value.premiumPriceStars,
        staleReservationSeconds: value.staleReservationSeconds,
        costAlertFileMb: value.costAlertFileMb,
        rolloutPercent: value.rolloutPercent,
        rolloutUserIds: value.rolloutUserIds,
      };
      const response = await fetch("/api/settings/monetization", {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Could not save settings");
      setValue(data); setMessage("Settings saved. New operations will use them immediately.");
      await loadHistory();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save settings");
    } finally { setSaving(false); }
  }

  return <AdminLayout><main className="dashboard-shell narrow-shell">
    <header className="topbar"><div><p className="eyebrow">Operations</p><h1>Monetization settings</h1><p className="page-intro">Run the v1 credits and referrals launch now, then enable premium payments later without changing Railway variables.</p></div></header>
    <section className="panel composer-card"><div className="notice"><strong>Safe controls</strong><span>Changes are validated, written to PostgreSQL, and audit logged. Existing balances are not changed when defaults change.</span></div>
      {loading ? <p className="muted">Loading settings…</p> : <form className="composer-form" onSubmit={save}>
        <label className="checkbox-label"><input type="checkbox" checked={value.enabled} onChange={(event) => setValue({ ...value, enabled: event.target.checked })} disabled={value.emergencyDisabled} /><span>Enable credits and referral enforcement</span></label>
        <label className="checkbox-label"><input type="checkbox" checked={value.premiumEnabled} onChange={(event) => setValue({ ...value, premiumEnabled: event.target.checked })} disabled={value.emergencyDisabled || !value.enabled} /><span>Enable premium subscriptions and Telegram Stars payments</span></label>
        {!value.premiumEnabled && <p className="muted">Premium is disabled for the v1 launch. Credits and referrals remain available.</p>}
        {value.emergencyDisabled && <p className="inline-error">Emergency disable is active through MONETIZATION_EMERGENCY_DISABLED. Turn that Railway variable off before enabling monetization here.</p>}
        <div className="entitlement-actions">
          {([ ["starterCredits", "Starter credits", 0, 1000], ["aiCreditCost", "AI request cost", 0, 1000], ["dailyDownloadLimit", "Daily downloads per user", 1, 500], ["aiTrials", "Legacy AI trials", 0, 100], ["premiumPriceStars", "Premium price (Stars)", 1, 100000], ["referralInviterReward", "Inviter reward", 0, 1000], ["referralInviteeReward", "Invitee reward", 0, 1000], ["referralRequiredDownloads", "Successful operations to qualify", 1, 100], ["referralMonthlyCap", "Referral cap / 30 days", 0, 100], ["rolloutPercent", "Rollout percentage", 0, 100], ["staleReservationSeconds", "Stale reservation seconds", 300, 86400], ["costAlertFileMb", "Large-file alert (MB)", 1, 4096] ] as const).map(([name, label, min, max]) => <label key={name}>{label}<input type="number" min={min} max={max} value={value[name]} onChange={(event) => setNumber(name, event.target.value)} /></label>)}
        </div>
        <label>Rollout user IDs<input value={value.rolloutUserIds.join(", ")} onChange={(event) => setValue({ ...value, rolloutUserIds: event.target.value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isSafeInteger(item) && item > 0) })} placeholder="Telegram IDs, comma separated" /></label>
        {error && <p className="form-error">{error}</p>}{message && <p className="form-success">{message}</p>}
        <div className="composer-actions"><span className="muted">Changes apply to new decisions immediately.</span><button className="button" disabled={saving}>{saving ? "Saving…" : "Save settings"}</button></div>
      </form>}
    </section>
    <section className="panel user-manager"><h2>Settings history</h2><div className="history-list">{history.map((item, index) => <article key={`${item.createdAt}-${index}`}><strong>{new Date(item.createdAt).toLocaleString()}</strong><span><span className="history-reason">{item.reason}</span><small className="history-change">{changedSummary(item.changed)}</small></span><small>{item.actor}</small></article>)}{!history.length && <p className="muted">No changes recorded yet.</p>}</div></section>
  </main></AdminLayout>;
}
