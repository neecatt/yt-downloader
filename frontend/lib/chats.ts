import "server-only";

export type Conversation = {
  chatId: number;
  username: string | null;
  displayName: string | null;
  updatedAt: string;
  lastText: string | null;
  lastDirection: "inbound" | "outbound" | null;
  lastMessageAt: string | null;
  unreadCount: number;
};

export type ChatMessage = {
  id: string;
  direction: "inbound" | "outbound";
  text: string;
  delivered: boolean;
  error: string | null;
  createdAt: string;
};

function apiUrl(path: string) {
  if (!process.env.ADMIN_API_URL) throw new Error("Chat API is not configured");
  return new URL(path, process.env.ADMIN_API_URL);
}

function headers() {
  const result: HeadersInit = { Accept: "application/json" };
  if (process.env.ADMIN_API_TOKEN) result.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`;
  return result;
}

export async function fetchConversations(q = "") {
  const url = apiUrl("/admin/conversations");
  if (q.trim()) url.searchParams.set("q", q.trim().slice(0, 100));
  url.searchParams.set("limit", "100");
  const response = await fetch(url, { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`Chat API returned ${response.status}`);
  return await response.json() as { conversations: Conversation[] };
}

export async function fetchMessages(chatId: number) {
  const url = apiUrl(`/admin/conversations/${encodeURIComponent(chatId)}/messages`);
  const response = await fetch(url, { headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`Chat API returned ${response.status}`);
  return await response.json() as { messages: ChatMessage[] };
}

export async function markConversationRead(chatId: number) {
  const response = await fetch(apiUrl(`/admin/conversations/${encodeURIComponent(chatId)}/read`), { method: "POST", headers: headers(), cache: "no-store", signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`Chat API returned ${response.status}`);
}

export async function replyToConversation(chatId: number, message: string) {
  const response = await fetch(apiUrl(`/admin/conversations/${encodeURIComponent(chatId)}/messages`), {
    method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
    body: JSON.stringify({ message }), cache: "no-store", signal: AbortSignal.timeout(30000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Chat API returned ${response.status}`);
  }
  return await response.json() as { sent: boolean };
}
