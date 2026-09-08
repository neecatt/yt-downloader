import "server-only";

function apiUrl(path: string) { if (!process.env.ADMIN_API_URL) throw new Error("Admin API is not configured"); return new URL(path, process.env.ADMIN_API_URL); }
function headers() { const result: HeadersInit = { Accept: "application/json" }; if (process.env.ADMIN_API_TOKEN) result.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`; return result; }
async function get<T>(path: string) { const response = await fetch(apiUrl(path), { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) }); if (!response.ok) throw new Error(`Admin API returned ${response.status}`); return await response.json() as T; }
export type UsageData = { totals: Record<string, number>; daily: { date: string; successfulOperations: number; aiRequests: number; summaries: number }[] };
export type CreditsData = { users: { userId: number; username: string | null; displayName: string | null; credits: number; reserved: number; createdAt: string; lastSeenAt: string; qualifiedReferrals: number; pendingReferrals: number; earned: number; spent: number }[]; page: number; pageSize: number; total: number; summary: Record<string, number> };
export type ReferralData = { referrals: { inviterId: number; inviteeId: number; status: string; suspiciousReason: string | null; createdAt: string; qualifiedAt: string | null; inviterUsername: string | null; inviteeUsername: string | null }[]; page: number; pageSize: number; total: number };
export type TransactionData = { transactions: { id: string; userId: number; username: string | null; displayName: string | null; delta: number; balanceAfter: number; reason: string; operationId: string | null; actor: string; createdAt: string }[]; page: number; pageSize: number; total: number };
export const fetchUsage = (days: number) => get<UsageData>(`/admin/usage?days=${Math.min(365, Math.max(1, days))}`);
export const fetchCredits = (q: string, page: number, pageSize = 25) => get<CreditsData>(`/admin/credits?q=${encodeURIComponent(q)}&page=${page}&pageSize=${pageSize}`);
export const fetchReferrals = (status: string, page: number, pageSize = 25) => get<ReferralData>(`/admin/referrals?${status ? `status=${encodeURIComponent(status)}&` : ""}page=${page}&pageSize=${pageSize}`);
export const fetchTransactions = (q: string, page: number, pageSize = 25) => get<TransactionData>(`/admin/transactions?q=${encodeURIComponent(q)}&page=${page}&pageSize=${pageSize}`);
