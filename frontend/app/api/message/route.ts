import { NextRequest, NextResponse } from "next/server";
import { messageUser } from "@/lib/messaging";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = await request.json();
    if (typeof body?.username !== "string" || !/^@?[A-Za-z0-9_]{5,32}$/.test(body.username.trim())) {
      return NextResponse.json({ error: "Enter a valid Telegram username" }, { status: 400 });
    }
    if (typeof body?.message !== "string" || !body.message.trim() || body.message.length > 4096) {
      return NextResponse.json({ error: "Message must contain 1 to 4096 characters" }, { status: 400 });
    }
    return NextResponse.json(await messageUser(body.username.trim(), body.message), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Could not send message" }, { status: 502 });
  }
}
