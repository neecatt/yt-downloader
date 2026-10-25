import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchUsage } from "@/lib/monetization-admin";

export const dynamic = "force-dynamic";

const TELEGRAM_USERNAME = /^[a-z0-9_]{5,32}$/;
const MAX_EXCLUDED_USERS = 50;

export async function GET(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const params = request.nextUrl.searchParams;
  const excluded = (params.get("excludeUsers") || "")
    .split(",")
    .map((value) => value.trim().replace(/^@/, "").toLowerCase())
    .filter(Boolean);
  if (excluded.length > MAX_EXCLUDED_USERS || excluded.some((value) => !TELEGRAM_USERNAME.test(value))) {
    return NextResponse.json({ error: "Enter up to 50 valid Telegram usernames." }, { status: 400 });
  }
  try {
    return NextResponse.json(
      await fetchUsage(Number(params.get("days")) || 30, [...new Set(excluded)]),
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json({ error: "Usage service unavailable" }, { status: 502 });
  }
}
