import { NextRequest, NextResponse } from "next/server";
import { fetchActivity } from "@/lib/activity";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const filters = {
    q: request.nextUrl.searchParams.get("q") || undefined,
    platform: request.nextUrl.searchParams.get("platform") || undefined,
    status: request.nextUrl.searchParams.get("status") || undefined,
    page: Number(request.nextUrl.searchParams.get("page") || 1),
    pageSize: Number(request.nextUrl.searchParams.get("pageSize") || 25),
  };
  try { return NextResponse.json(await fetchActivity(filters), { headers: { "Cache-Control": "no-store" } }); }
  catch { return NextResponse.json({ error: "Activity service unavailable" }, { status: 502 }); }
}
