import "server-only";

export type AccountUser = {
  user_id: number; chat_id: number | null; username: string | null; display_name: string | null;
  credits: number; reserved_credits: number; ai_trials: number; reserved_ai_trials: number;
  successful_downloads: number; complimentary: boolean; premium: boolean;
  subscription_expires_at: string | null; subscription_cancelled: boolean;
  qualified_referrals: number; pending_referrals: number; suspicious_referrals: number;
  successful_operations: number; last_seen_at: string;
};
export type UserHistory = { type: string; reason: string; actor: string; details: string | null; createdAt: string };

function apiUrl(path: string) { if (!process.env.ADMIN_API_URL) throw new Error("Users API is not configured"); return new URL(path, process.env.ADMIN_API_URL); }
function headers(json = false) { const result: HeadersInit = { Accept: "application/json" }; if (json) result["Content-Type"] = "application/json"; if (process.env.ADMIN_API_TOKEN) result.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`; return result; }

export async function fetchUsers(q: string, access: string, page: number, pageSize: number) {
  const url=apiUrl("/admin/users"); if(q) url.searchParams.set("q",q.slice(0,100)); if(access) url.searchParams.set("access",access); url.searchParams.set("page",String(page)); url.searchParams.set("pageSize",String(pageSize));
  const response=await fetch(url,{headers:headers(),cache:"no-store",signal:AbortSignal.timeout(8000)}); if(!response.ok) throw new Error(`Users API returned ${response.status}`);
  return await response.json() as { users: AccountUser[]; page:number; pageSize:number; total:number };
}
export async function updateUser(userId:number,payload:{creditAdjustment?:number;aiTrials?:number;complimentary?:boolean;reason:string}) { const response=await fetch(apiUrl(`/admin/users/${userId}`),{method:"PATCH",headers:headers(true),body:JSON.stringify(payload),cache:"no-store",signal:AbortSignal.timeout(8000)}); if(!response.ok) throw new Error((await response.json().catch(()=>null))?.detail||"Could not update user"); return await response.json(); }
export async function fetchUserHistory(userId:number) { const response=await fetch(apiUrl(`/admin/users/${userId}/history`),{headers:headers(),cache:"no-store",signal:AbortSignal.timeout(8000)}); if(!response.ok) throw new Error("Could not load user history"); return await response.json() as {history:UserHistory[]}; }
