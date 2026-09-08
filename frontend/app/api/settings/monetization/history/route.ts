import { NextResponse } from "next/server";
import { hasValidSession } from "@/lib/auth";
import { fetchMonetizationSettingsHistory } from "@/lib/settings";

export const dynamic = "force-dynamic";

export async function GET() {
  if (!(await hasValidSession())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    return NextResponse.json(await fetchMonetizationSettingsHistory(), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "Settings history service unavailable" }, { status: 502 });
  }
}
