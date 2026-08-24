import { NextRequest, NextResponse } from "next/server";
import { fetchMessages, replyToConversation } from "@/lib/chats";
import { hasValidSession } from "@/lib/auth";

export const dynamic = "force-dynamic";

async function chatId(params: Promise<{ chatId: string }>) {
  const value = Number((await params).chatId);
  return Number.isSafeInteger(value) ? value : null;
}

export async function GET(_request: NextRequest, { params }: { params: Promise<{ chatId: string }> }) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const id = await chatId(params);
  if (id === null) return NextResponse.json({ error: "Invalid chat" }, { status: 400 });
  try { return NextResponse.json(await fetchMessages(id), { headers: { "Cache-Control": "no-store" } }); }
  catch { return NextResponse.json({ error: "Chat service unavailable" }, { status: 502 }); }
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ chatId: string }> }) {
  if (!(await hasValidSession())) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const id = await chatId(params);
  if (id === null) return NextResponse.json({ error: "Invalid chat" }, { status: 400 });
  try {
    const body = await request.json();
    if (typeof body?.message !== "string" || !body.message.trim() || body.message.length > 4096) {
      return NextResponse.json({ error: "Message must contain 1 to 4096 characters" }, { status: 400 });
    }
    return NextResponse.json(await replyToConversation(id, body.message), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Could not send message" }, { status: 502 });
  }
}
