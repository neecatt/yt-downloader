import { NextRequest, NextResponse } from "next/server";
import { deleteActivity, fetchActivity } from "@/lib/activity";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

function boundedInteger(value: string | null, fallback: number, maximum: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) ? Math.min(maximum, Math.max(1, parsed)) : fallback;
}

export async function GET(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const filters = {
    q: request.nextUrl.searchParams.get("q") || undefined,
    platform: request.nextUrl.searchParams.get("platform") || undefined,
    status: request.nextUrl.searchParams.get("status") || undefined,
    action: request.nextUrl.searchParams.get("action") || undefined,
    excludeUsers: (request.nextUrl.searchParams.get("excludeUsers") || "").split(",").map((value) => value.trim()).filter(Boolean).slice(0, 50),
    page: boundedInteger(request.nextUrl.searchParams.get("page"), 1, 1_000_000),
    pageSize: boundedInteger(request.nextUrl.searchParams.get("pageSize"), 25, 100),
  };
  try { return NextResponse.json(await fetchActivity(filters), { headers: { "Cache-Control": "no-store" } }); }
  catch { return NextResponse.json({ error: "Activity service unavailable" }, { status: 502 }); }
}

export async function DELETE(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = await request.json();
    if (!Array.isArray(body?.ids) || body.ids.length < 1 || body.ids.length > 100 || !body.ids.every((id: unknown) => typeof id === "string" && /^[a-f0-9]{32}$/.test(id))) {
      return NextResponse.json({ error: "Invalid IDs" }, { status: 400 });
    }
    return NextResponse.json(await deleteActivity(body.ids), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Could not delete activity" }, { status: 502 });
  }
}
