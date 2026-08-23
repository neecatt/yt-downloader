import { NextRequest, NextResponse } from "next/server";
import { broadcastMessage } from "@/lib/messaging";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = await request.json();
    if (typeof body?.message !== "string" || !body.message.trim() || body.message.length > 4096) {
      return NextResponse.json({ error: "Message must contain 1 to 4096 characters" }, { status: 400 });
    }
    return NextResponse.json(await broadcastMessage(body.message), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Could not send broadcast" }, { status: 502 });
  }
}
