import "server-only";

type DeliveryResult = { targeted: number; sent: number; failed: number; username?: string };

async function sendAdminMessage(path: string, payload: Record<string, string>): Promise<DeliveryResult> {
  if (!process.env.ADMIN_API_URL) throw new Error("Messaging API is not configured");
  const url = new URL(path, process.env.ADMIN_API_URL);
  const headers: HeadersInit = { Accept: "application/json", "Content-Type": "application/json" };
  if (process.env.ADMIN_API_TOKEN) headers.Authorization = `Bearer ${process.env.ADMIN_API_TOKEN}`;
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
    cache: "no-store",
    signal: AbortSignal.timeout(120000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail || `Messaging API returned ${response.status}`);
  }
  return await response.json() as DeliveryResult;
}

export function broadcastMessage(message: string) {
  return sendAdminMessage("/admin/broadcast", { message });
}

export function messageUser(username: string, message: string) {
  return sendAdminMessage("/admin/message", { username, message });
}
