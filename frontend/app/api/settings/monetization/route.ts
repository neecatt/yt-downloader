import { NextRequest, NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchMonetizationSettings, updateMonetizationSettings } from "@/lib/settings";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try { return NextResponse.json(await fetchMonetizationSettings(), { headers: { "Cache-Control": "no-store" } }); }
  catch { return NextResponse.json({ error: "Settings service unavailable" }, { status: 502 }); }
}

export async function PATCH(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try { return NextResponse.json(await updateMonetizationSettings(await request.json()), { headers: { "Cache-Control": "no-store" } }); }
  catch (error) { return NextResponse.json({ error: error instanceof Error ? error.message : "Settings update failed" }, { status: 502 }); }
}
