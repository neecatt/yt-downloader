import { NextResponse } from "next/server";
import { createSessionValue, COOKIE_NAME, isDashboardConfigured, sessionCookieOptions, validAdminToken } from "@/lib/auth";

const failedAttempts = new Map<string, { startedAt: number; count: number }>();
const WINDOW_MS = 15 * 60 * 1000;
const MAX_ATTEMPTS = 10;

function clientKey(request: Request) {
  return request.headers.get("x-real-ip") || request.headers.get("x-forwarded-for")?.split(",", 1)[0]?.trim() || "unknown";
}

function allowed(request: Request) {
  const key = clientKey(request);
  const now = Date.now();
  const current = failedAttempts.get(key);
  if (!current || now - current.startedAt >= WINDOW_MS) {
    failedAttempts.set(key, { startedAt: now, count: 0 });
    return true;
  }
  return current.count < MAX_ATTEMPTS;
}

function recordFailure(request: Request) {
  const key = clientKey(request);
  const current = failedAttempts.get(key) || { startedAt: Date.now(), count: 0 };
  current.count += 1;
  failedAttempts.set(key, current);
  if (failedAttempts.size > 10000) {
    const cutoff = Date.now() - WINDOW_MS;
    for (const [candidate, attempt] of failedAttempts) {
      if (attempt.startedAt < cutoff) failedAttempts.delete(candidate);
    }
  }
}

export async function POST(request: Request) {
  if (!isDashboardConfigured()) return NextResponse.json({ error: "Dashboard is not configured" }, { status: 503 });
  if (!allowed(request)) return NextResponse.json({ error: "Too many attempts" }, { status: 429, headers: { "Retry-After": "900" } });
  const contentLength = Number(request.headers.get("content-length") || 0);
  if (contentLength > 1024) return NextResponse.json({ error: "Invalid request" }, { status: 400 });
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Invalid request" }, { status: 400 }); }
  const token = typeof body === "object" && body !== null && "token" in body && typeof body.token === "string" ? body.token : "";
  const remember = typeof body === "object" && body !== null && "remember" in body && body.remember === true;
  if (!validAdminToken(token)) {
    recordFailure(request);
    return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(COOKIE_NAME, createSessionValue(remember), sessionCookieOptions(remember));
  return response;
}
