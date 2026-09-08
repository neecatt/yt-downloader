import "server-only";

export type MonetizationSettings = {
  enabled: boolean; premiumEnabled: boolean; starterCredits: number; aiCreditCost: number; dailyDownloadLimit: number; aiTrials: number;
  referralInviterReward: number; referralInviteeReward: number;
  referralRequiredDownloads: number; referralMonthlyCap: number;
  premiumPriceStars: number; staleReservationSeconds: number;
  costAlertFileMb: number; rolloutPercent: number; rolloutUserIds: number[];
  emergencyDisabled: boolean;
};
export type MonetizationSettingsAudit = { changed: Record<string, unknown>; reason: string; actor: string; createdAt: string };

function apiUrl(path: string) { if (!process.env.ADMIN_API_URL) throw new Error("Settings API is not configured"); return new URL(path, process.env.ADMIN_API_URL); }
function headers(json = false): HeadersInit { const result: HeadersInit = { Accept: "application/json" }; if (json) result["Content-Type"] = "application/json"; if (process.env.ADMIN_API_TOKEN) result.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`; return result; }

export async function fetchMonetizationSettings() {
  const response = await fetch(apiUrl("/admin/settings/monetization"), { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error("Could not load monetization settings");
  return await response.json() as MonetizationSettings;
}

export async function updateMonetizationSettings(payload: Partial<MonetizationSettings> & { reason: string }) {
  const response = await fetch(apiUrl("/admin/settings/monetization"), { method: "PATCH", headers: headers(true), body: JSON.stringify(payload), cache: "no-store", signal: AbortSignal.timeout(8000) });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.detail || "Could not update monetization settings");
  return data as MonetizationSettings;
}

export async function fetchMonetizationSettingsHistory() {
  const response = await fetch(apiUrl("/admin/settings/monetization/history"), { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error("Could not load settings history");
  return await response.json() as { history: MonetizationSettingsAudit[] };
}
