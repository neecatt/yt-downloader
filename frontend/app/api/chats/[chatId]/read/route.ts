import { NextResponse } from "next/server";
import { markConversationRead } from "@/lib/chats";
import { hasValidSession } from "@/lib/auth";

export async function POST(_request: Request, { params }: { params: Promise<{ chatId: string }> }) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const id = Number((await params).chatId);
  if (!Number.isSafeInteger(id)) return NextResponse.json({ error: "Invalid chat" }, { status: 400 });
  try { await markConversationRead(id); return NextResponse.json({ ok: true }); }
  catch { return NextResponse.json({ error: "Chat service unavailable" }, { status: 502 }); }
}
