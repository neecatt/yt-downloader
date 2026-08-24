import { NextRequest, NextResponse } from "next/server";
import { fetchConversations } from "@/lib/chats";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    return NextResponse.json(await fetchConversations(request.nextUrl.searchParams.get("q") || ""), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Chat service unavailable" }, { status: 502 });
  }
}
