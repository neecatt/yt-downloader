import { NextRequest, NextResponse } from "next/server";
import { fetchFeedback } from "@/lib/feedback";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    return NextResponse.json(await fetchFeedback(request.nextUrl.searchParams.get("status") || "", request.nextUrl.searchParams.get("q") || ""), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ error: "Feedback service unavailable" }, { status: 502 }); }
}
