import { NextResponse } from "next/server";
import { createSessionValue, COOKIE_NAME, isDashboardConfigured, sessionCookieOptions, validAdminToken } from "@/lib/auth";

export async function POST(request: Request) {
  if (!isDashboardConfigured()) return NextResponse.json({ error: "Dashboard is not configured" }, { status: 503 });
  let body: unknown;
  try { body = await request.json(); } catch { return NextResponse.json({ error: "Invalid request" }, { status: 400 }); }
  const token = typeof body === "object" && body !== null && "token" in body && typeof body.token === "string" ? body.token : "";
  if (!validAdminToken(token)) return NextResponse.json({ error: "Invalid credentials" }, { status: 401 });
  const response = NextResponse.json({ ok: true });
  response.cookies.set(COOKIE_NAME, createSessionValue(), sessionCookieOptions());
  return response;
}
