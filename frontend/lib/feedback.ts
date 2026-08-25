import "server-only";

export type FeedbackItem = {
  id: string;
  telegramUsername: string | null;
  telegramDisplayName: string | null;
  feedback: string;
  status: "new" | "reviewed";
  createdAt: string;
  reviewedAt: string | null;
};

function apiUrl(path: string) {
  if (!process.env.ADMIN_API_URL) throw new Error("Feedback API is not configured");
  return new URL(path, process.env.ADMIN_API_URL);
}

function headers() {
  const result: HeadersInit = { Accept: "application/json" };
  if (process.env.ADMIN_API_TOKEN) result.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`;
  return result;
}

export async function fetchFeedback(status = "", q = "") {
  const url = apiUrl("/admin/feedback");
  if (status) url.searchParams.set("status", status);
  if (q.trim()) url.searchParams.set("q", q.trim().slice(0, 100));
  url.searchParams.set("pageSize", "100");
  const response = await fetch(url, { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`Feedback API returned ${response.status}`);
  return await response.json() as { feedbacks: FeedbackItem[]; total: number; newCount: number };
}

export async function updateFeedback(id: string, status: "new" | "reviewed") {
  const response = await fetch(apiUrl(`/admin/feedback/${encodeURIComponent(id)}`), {
    method: "PATCH", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ status }), cache: "no-store", signal: AbortSignal.timeout(8000),
  });
  if (!response.ok) throw new Error("Could not update feedback");
}

export async function deleteFeedback(id: string) {
  const response = await fetch(apiUrl(`/admin/feedback/${encodeURIComponent(id)}`), { method: "DELETE", headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error("Could not delete feedback");
}
